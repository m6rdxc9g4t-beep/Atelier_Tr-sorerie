// Serveur Flask lancé par l'application de bureau : Python enregistré à l'installation (celui qui a les
// dépendances du projet), `app.py --desktop`, journal dans un fichier. Sans Electron (testable avec Node).
'use strict'

const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const DEFAULT_PORT = 5050 // 5000 est pris par le récepteur AirPlay sur macOS
const REQUIRED_MODULES = 'import flask, openpyxl, dotenv'

/** Lit PORT dans le fichier .env du projet (sans l'interpréter entièrement) : l'application suit sa configuration. */
function readPort(repo, env = process.env) {
  let value = env.PORT
  if (value === undefined) {
    try {
      for (const line of fs.readFileSync(path.join(repo, '.env'), 'utf8').split(/\r?\n/)) {
        const match = /^\s*(?:export\s+)?PORT\s*=\s*["']?(\d+)["']?/.exec(line)
        if (match) value = match[1]
      }
    } catch {
      /* pas de .env : port par défaut */
    }
  }
  const port = Number(value)
  return Number.isInteger(port) && port > 0 && port < 65536 ? port : DEFAULT_PORT
}

/**
 * Qui répond à cette adresse ?
 *   'atelier' : Atelier Trésorerie (lancé depuis un terminal ou une autre instance)
 *   'other'   : un autre programme occupe le port
 *   'down'    : personne
 */
async function appStatus(baseUrl, timeoutMs = 1500) {
  try {
    const response = await fetch(`${baseUrl}/api/ping`, { signal: AbortSignal.timeout(timeoutMs) })
    const body = await response.json().catch(() => null)
    return response.ok && body && body.app === 'atelier-tresorerie' ? 'atelier' : 'other'
  } catch {
    return 'down'
  }
}

/** Python utilisable et dépendances présentes ? */
function pythonReady(python, repo) {
  const result = spawnSync(python, ['-c', REQUIRED_MODULES], { cwd: repo, encoding: 'utf8', timeout: 30_000 })
  if (result.error) return { ok: false, missing: true, detail: result.error.message }
  return { ok: result.status === 0, missing: false, detail: (result.stderr || '').trim().split('\n').pop() }
}

/** Après un « git pull » ajoutant une dépendance : installation automatique (journalisée). */
async function ensurePythonDeps({ python, repo, logFile, onStatus = () => {} }) {
  const first = pythonReady(python, repo)
  if (first.ok) return
  if (first.missing) {
    throw new Error(`Python introuvable : ${python}\nDepuis le dossier du projet, relancer : bash scripts/macos/install-desktop.sh`)
  }
  onStatus('Installation des dépendances Python…')
  const log = fs.openSync(logFile, 'a')
  const code = await new Promise((resolve) => {
    const child = spawn(python, ['-m', 'pip', 'install', '-r', 'requirements.txt'], { cwd: repo, stdio: ['ignore', log, log] })
    child.once('error', () => resolve(-1))
    child.once('exit', (status) => resolve(status))
  })
  fs.closeSync(log)
  const second = pythonReady(python, repo)
  if (code !== 0 || !second.ok) {
    throw new Error(`Dépendances Python manquantes (${second.detail || first.detail}).\nDans un terminal : "${python}" -m pip install -r requirements.txt`)
  }
}

/**
 * Lance `python app.py --desktop` et attend /api/ping. Renvoie { child, stop() }.
 * Rejette si le processus s'arrête ou ne répond pas dans le délai (le journal donne la cause).
 */
async function startServer({ python, repo, port, logFile, env = process.env, timeoutMs = 45_000 }) {
  const baseUrl = `http://127.0.0.1:${port}`
  const log = fs.openSync(logFile, 'a')
  const child = spawn(python, ['app.py', '--desktop'], {
    cwd: repo,
    env: { ...env, PORT: String(port), PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', log, log],
  })
  fs.closeSync(log)
  let exited = null
  child.once('exit', (code, signal) => (exited = { code, signal }))
  const failed = new Promise((_, reject) => child.once('error', reject))
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (exited) throw new Error(`Le serveur s’est arrêté au démarrage (code ${exited.code ?? exited.signal}).`)
    const status = await Promise.race([appStatus(baseUrl, 1000), failed])
    if (status === 'atelier') return { child, url: baseUrl, stop: () => stopProcess(child) }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  await stopProcess(child)
  throw new Error(`Le serveur ne répond pas après ${Math.round(timeoutMs / 1000)} s.`)
}

/** SIGTERM (arrêt propre), puis SIGKILL après 5 s. */
function stopProcess(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) return resolve()
    const timer = setTimeout(() => child.kill('SIGKILL'), 5000)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    child.kill('SIGTERM')
  })
}

module.exports = { DEFAULT_PORT, readPort, appStatus, pythonReady, ensurePythonDeps, startServer, stopProcess }
