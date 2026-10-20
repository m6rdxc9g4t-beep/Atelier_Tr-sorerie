// Atelier Trésorerie — application de bureau (Electron), sur le modèle d'Atelier Projets.
// Une fenêtre native, sans navigateur : au lancement, vérifie Python et ses dépendances, démarre le serveur
// Flask local (`app.py --desktop`) et affiche l'interface ; Cmd+Q arrête tout. Si l'application tourne déjà
// dans un terminal (python app.py), la fenêtre l'utilise sans rien relancer.
//
// Lancée par « Atelier Trésorerie.app » (scripts/macos/install-desktop.sh), qui fixe ATELIER_REPO,
// ATELIER_PYTHON et le PATH, ou directement : npm start --prefix desktop
'use strict'

const { app, BrowserWindow, Menu, dialog, screen, shell } = require('electron')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { appStatus, ensurePythonDeps, readPort, startServer } = require('./lib/server.cjs')

const REPO = path.resolve(process.env.ATELIER_REPO || path.join(__dirname, '..'))
const PYTHON = process.env.ATELIER_PYTHON || 'python3'
const PRODUCT = 'Atelier Trésorerie'

app.setName(PRODUCT)
const LOG_DIR =
  process.env.ATELIER_LOG_DIR ||
  (process.platform === 'darwin' ? path.join(os.homedir(), 'Library', 'Logs', 'Atelier_Tresorerie') : path.join(app.getPath('userData'), 'logs'))
const LOG_FILE = path.join(LOG_DIR, 'app.log')
fs.mkdirSync(LOG_DIR, { recursive: true })

function log(message) {
  fs.appendFileSync(LOG_FILE, `[${new Date().toLocaleString('fr-FR')}] ${message}\n`)
}

/** Ce que l'application a lancé elle-même (et doit donc arrêter en quittant). */
const owned = { server: null }
let mainWindow = null
let baseUrl = null
let quitting = false

// --- Fenêtre ------------------------------------------------------------------------------------------

const STATE_FILE = path.join(app.getPath('userData'), 'window-state.json')

function loadBounds() {
  try {
    const bounds = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
    // Fenêtre encore visible sur un des écrans (écran externe débranché depuis).
    const visible = screen.getAllDisplays().some(({ workArea: area }) =>
      bounds.x < area.x + area.width && bounds.x + bounds.width > area.x && bounds.y < area.y + area.height && bounds.y + bounds.height > area.y,
    )
    return visible ? bounds : { width: bounds.width, height: bounds.height }
  } catch {
    return { width: 1440, height: 920 }
  }
}

function saveBounds() {
  if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isMinimized() || mainWindow.isFullScreen()) return
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify({ ...mainWindow.getNormalBounds(), maximized: mainWindow.isMaximized() }))
  } catch {
    /* préférence non mémorisée */
  }
}

function isInternal(url) {
  return Boolean(baseUrl) && (url === baseUrl || url.startsWith(`${baseUrl}/`))
}

function createWindow() {
  const bounds = loadBounds()
  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 900,
    minHeight: 600,
    title: PRODUCT,
    show: false,
    backgroundColor: '#090B14', // ≈ --atelier-bg sombre (bleu roi 6 % dans #07070A) : pas de flash blanc au démarrage
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: true },
  })
  if (bounds.maximized) mainWindow.maximize()
  mainWindow.once('ready-to-show', () => mainWindow.show())
  for (const event of ['resize', 'move']) mainWindow.on(event, saveBounds)
  mainWindow.on('close', saveBounds)
  mainWindow.on('closed', () => (mainWindow = null))

  const contents = mainWindow.webContents
  // Liens externes (Ollama, Claude Console, GitHub…) : navigateur par défaut, jamais dans la fenêtre.
  contents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url) && !isInternal(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  contents.on('will-navigate', (event, url) => {
    if (isInternal(url) || url.startsWith('file://')) return
    event.preventDefault()
    if (/^https?:\/\//.test(url)) void shell.openExternal(url)
  })
  // Sauvegarde de la base : proposée dans Téléchargements, avec la fenêtre d'enregistrement de macOS.
  contents.session.on('will-download', (_event, item) => {
    item.setSaveDialogOptions({ defaultPath: path.join(app.getPath('downloads'), item.getFilename()) })
    item.once('done', (_e, state) => {
      if (state === 'completed') log(`Fichier enregistré : ${item.getSavePath()}`)
    })
  })
  contents.on('did-fail-load', (_event, code, description, url) => {
    if (isInternal(url) && code !== -3) log(`Chargement échoué (${code} ${description}) : ${url}`)
  })
  return mainWindow
}

function setStatus(text, hint = '') {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const contents = mainWindow.webContents
  if (!contents.getURL().startsWith('file://')) return
  contents.executeJavaScript(`window.setStatus && window.setStatus(${JSON.stringify(text)}, ${JSON.stringify(hint)})`).catch(() => undefined)
}

function go(route) {
  if (mainWindow && baseUrl) void mainWindow.loadURL(`${baseUrl}${route}`)
}

// --- Menu ---------------------------------------------------------------------------------------------

function buildMenu() {
  const isMac = process.platform === 'darwin'
  const pages = [
    ['Tableau de bord', '/', '1'],
    ['Comptes & Soldes', '/accounts', '2'],
    ['Placements', '/investments', '3'],
    ['Transactions', '/transactions', '4'],
    ['Budgets & Objectifs', '/budgets', '5'],
    ['Assistant IA', '/ai-insights', '6'],
  ]
  const template = [
    ...(isMac
      ? [
          {
            label: PRODUCT,
            submenu: [
              { role: 'about', label: `À propos d’${PRODUCT}` },
              { type: 'separator' },
              { label: 'Paramètres…', accelerator: 'CmdOrCtrl+,', click: () => go('/settings') },
              { type: 'separator' },
              { role: 'hide', label: `Masquer ${PRODUCT}` },
              { role: 'hideOthers', label: 'Masquer les autres' },
              { role: 'unhide', label: 'Tout afficher' },
              { type: 'separator' },
              { role: 'quit', label: `Quitter ${PRODUCT}` },
            ],
          },
        ]
      : []),
    {
      label: 'Édition',
      submenu: [
        { role: 'undo', label: 'Annuler' },
        { role: 'redo', label: 'Rétablir' },
        { type: 'separator' },
        { role: 'cut', label: 'Couper' },
        { role: 'copy', label: 'Copier' },
        { role: 'paste', label: 'Coller' },
        { role: 'pasteAndMatchStyle', label: 'Coller sans mise en forme' },
        { role: 'selectAll', label: 'Tout sélectionner' },
      ],
    },
    {
      label: 'Aller',
      submenu: [
        ...pages.map(([label, route, key]) => ({ label, accelerator: `CmdOrCtrl+${key}`, click: () => go(route) })),
        { type: 'separator' },
        { label: 'Précédent', accelerator: 'CmdOrCtrl+[', click: () => mainWindow?.webContents.navigationHistory.goBack() },
        { label: 'Suivant', accelerator: 'CmdOrCtrl+]', click: () => mainWindow?.webContents.navigationHistory.goForward() },
      ],
    },
    {
      label: 'Présentation',
      submenu: [
        { role: 'reload', label: 'Actualiser' },
        { role: 'forceReload', label: 'Forcer l’actualisation' },
        { type: 'separator' },
        { role: 'resetZoom', label: 'Taille réelle' },
        { role: 'zoomIn', label: 'Agrandir' },
        { role: 'zoomOut', label: 'Réduire' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: 'Plein écran' },
        { role: 'toggleDevTools', label: 'Outils de développement' },
      ],
    },
    { role: 'windowMenu', label: 'Fenêtre' },
    {
      role: 'help',
      label: 'Aide',
      submenu: [
        { label: 'Journal de l’application', click: () => void shell.openPath(LOG_FILE) },
        { label: 'Ouvrir dans le navigateur', click: () => baseUrl && void shell.openExternal(baseUrl) },
        { label: 'Afficher le dossier du projet dans le Finder', click: () => void shell.openPath(REPO) },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// --- Démarrage ----------------------------------------------------------------------------------------

async function start() {
  log(`===== Démarrage (projet ${REPO}, Python ${PYTHON}) =====`)
  if (!fs.existsSync(path.join(REPO, 'app.py'))) {
    throw new Error(`Dossier du projet introuvable : ${REPO}\nDepuis le dossier du projet (déplacé ?), relancer : bash scripts/macos/install-desktop.sh`)
  }
  const port = readPort(REPO)
  const url = `http://127.0.0.1:${port}`
  const status = await appStatus(url)
  if (status === 'other') {
    throw new Error(`Le port ${port} est occupé par une autre application.\nChanger PORT dans le fichier .env du projet.`)
  }
  if (status === 'atelier') {
    log(`Serveur déjà en marche sur ${url} (python app.py ?) : utilisé tel quel.`)
    return url
  }

  setStatus('Vérification de Python…')
  await ensurePythonDeps({
    python: PYTHON,
    repo: REPO,
    logFile: LOG_FILE,
    onStatus: (text) => setStatus(text, 'Après une mise à jour : cela peut prendre une minute.'),
  })

  setStatus('Démarrage du serveur local…')
  owned.server = await startServer({ python: PYTHON, repo: REPO, port, logFile: LOG_FILE })
  log(`Serveur démarré sur ${url} (pid ${owned.server.child.pid}).`)
  owned.server.child.once('exit', (code, signal) => {
    if (quitting) return
    log(`Le serveur s’est arrêté (code ${code ?? signal}).`)
    void showFatal(new Error('Le serveur local s’est arrêté de façon inattendue.'))
  })
  return url
}

async function showFatal(error) {
  const message = error instanceof Error ? error.message : String(error)
  log(`ERREUR : ${message}`)
  const { response } = await dialog.showMessageBox(mainWindow ?? undefined, {
    type: 'error',
    title: PRODUCT,
    message: 'Atelier Trésorerie n’a pas pu démarrer',
    detail: `${message}\n\nLe journal donne le détail : ${LOG_FILE}`,
    buttons: ['Ouvrir le journal', 'Réessayer', 'Quitter'],
    defaultId: 1,
    cancelId: 2,
  })
  if (response === 0) {
    await shell.openPath(LOG_FILE)
    return showFatal(error)
  }
  if (response === 1) {
    await shutdown()
    quitting = false
    return launch()
  }
  app.quit()
}

async function launch() {
  if (!mainWindow) createWindow()
  await mainWindow.loadFile(path.join(__dirname, 'splash.html'))
  try {
    baseUrl = await start()
    await mainWindow.loadURL(`${baseUrl}/`)
  } catch (error) {
    await showFatal(error)
  }
}

async function shutdown() {
  quitting = true
  const { server } = owned
  owned.server = null
  if (server) {
    log('Arrêt du serveur.')
    await server.stop()
  }
}

// --- Cycle de vie -------------------------------------------------------------------------------------

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })

  app.whenReady().then(() => {
    buildMenu()
    void launch()
  })

  // Fermer la fenêtre quitte l'application (et arrête le serveur qu'elle a lancé).
  app.on('window-all-closed', () => app.quit())

  let stopped = false
  app.on('before-quit', (event) => {
    if (stopped) return
    event.preventDefault()
    void shutdown().finally(() => {
      stopped = true
      app.quit()
    })
  })
}
