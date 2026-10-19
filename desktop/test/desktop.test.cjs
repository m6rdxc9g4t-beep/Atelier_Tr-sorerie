// Application de bureau : lecture du port, détection d'une instance en marche, démarrage et arrêt du
// serveur Flask. Sans Electron. Lancer : npm test --prefix desktop
'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const os = require('node:os')
const path = require('node:path')
const { after, before, describe, it } = require('node:test')
const { appStatus, ensurePythonDeps, pythonReady, readPort, startServer } = require('../lib/server.cjs')

const REPO = path.join(__dirname, '..', '..')
const PYTHON = process.env.ATELIER_PYTHON || 'python3'

let dir

before(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'atelier-tresorerie-desktop-'))
})

after(() => fs.rmSync(dir, { recursive: true, force: true }))

function freePort() {
  return new Promise((resolve) => {
    const server = net.createServer().listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

describe('configuration', () => {
  it('lit PORT dans .env, sinon 5050', () => {
    assert.equal(readPort(dir, {}), 5050)
    fs.writeFileSync(path.join(dir, '.env'), '# commentaire\nOLLAMA_URL=http://localhost:11434\nexport PORT="5123"\n')
    assert.equal(readPort(dir, {}), 5123)
    assert.equal(readPort(dir, { PORT: '6000' }), 6000) // la variable d'environnement prime
    assert.equal(readPort(dir, { PORT: 'abc' }), 5050)
  })
})

describe('détection', () => {
  it('distingue Atelier Trésorerie, un autre programme et un port libre', async () => {
    const atelier = http.createServer((_q, r) => r.end(JSON.stringify({ app: 'atelier-tresorerie' })))
    const other = http.createServer((_q, r) => {
      r.writeHead(403)
      r.end('AirPlay')
    })
    await new Promise((resolve) => atelier.listen(0, '127.0.0.1', resolve))
    await new Promise((resolve) => other.listen(0, '127.0.0.1', resolve))
    try {
      assert.equal(await appStatus(`http://127.0.0.1:${atelier.address().port}`), 'atelier')
      assert.equal(await appStatus(`http://127.0.0.1:${other.address().port}`), 'other')
      assert.equal(await appStatus(`http://127.0.0.1:${await freePort()}`), 'down')
    } finally {
      atelier.close()
      other.close()
    }
  })
})

describe('serveur Flask', () => {
  it('vérifie Python et ses dépendances', async () => {
    assert.equal(pythonReady(PYTHON, REPO).ok, true)
    const missing = pythonReady(path.join(dir, 'pas-de-python'), REPO)
    assert.equal(missing.ok, false)
    assert.equal(missing.missing, true)
    await assert.rejects(
      ensurePythonDeps({ python: path.join(dir, 'pas-de-python'), repo: REPO, logFile: path.join(dir, 'log.txt') }),
      /Python introuvable/,
    )
  })

  it('démarre app.py --desktop, répond, puis s’arrête proprement', { timeout: 60_000 }, async () => {
    const port = await freePort()
    const logFile = path.join(dir, 'server.log')
    const server = await startServer({
      python: PYTHON,
      repo: REPO,
      port,
      logFile,
      env: { ...process.env, DATABASE_PATH: path.join(dir, 'test.db') },
    })
    try {
      const page = await fetch(`${server.url}/`)
      assert.equal(page.status, 200)
      assert.match(await page.text(), /Atelier/)
      const ping = await (await fetch(`${server.url}/api/ping`)).json()
      assert.equal(ping.app_mode, false) // pas de bouton « Quitter » : c'est Cmd+Q qui arrête
    } finally {
      await server.stop()
    }
    assert.equal(await appStatus(server.url), 'down')
    assert.match(fs.readFileSync(logFile, 'utf8'), new RegExp(`127\\.0\\.0\\.1:${port}`))
  })

  it('signale un serveur qui s’arrête au démarrage', { timeout: 30_000 }, async () => {
    const fakeRepo = path.join(dir, 'casse')
    fs.mkdirSync(fakeRepo, { recursive: true })
    fs.writeFileSync(path.join(fakeRepo, 'app.py'), 'import sys\nsys.exit(3)\n')
    await assert.rejects(
      startServer({ python: PYTHON, repo: fakeRepo, port: await freePort(), logFile: path.join(dir, 'casse.log') }),
      /arrêté au démarrage \(code 3\)/,
    )
  })
})
