const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const net = require('net');

let mainWindow = null;
let streamlitProcess = null;
const STREAMLIT_PORT = 8501;

// ── Paths ──────────────────────────────────────────────────────────
function getAppPath() {
  // In packaged app, resources are in extraResources/app
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'app');
  }
  // In dev, the parent directory is the project root
  return path.join(__dirname, '..');
}

function getEnvPath() {
  return path.join(getAppPath(), '.env');
}

// ── Port check ─────────────────────────────────────────────────────
function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(true));
    server.once('listening', () => {
      server.close();
      resolve(false);
    });
    server.listen(port);
  });
}

function waitForPort(port, timeout = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const socket = new net.Socket();
      socket.setTimeout(500);
      socket.once('connect', () => {
        socket.destroy();
        resolve();
      });
      socket.once('timeout', () => {
        socket.destroy();
        if (Date.now() - start > timeout) {
          reject(new Error('Streamlit server did not start in time'));
        } else {
          setTimeout(check, 500);
        }
      });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() - start > timeout) {
          reject(new Error('Streamlit server did not start in time'));
        } else {
          setTimeout(check, 500);
        }
      });
      socket.connect(port, '127.0.0.1');
    };
    check();
  });
}

// ── First-run API key check ────────────────────────────────────────
function hasApiKey() {
  const envPath = getEnvPath();
  if (!fs.existsSync(envPath)) return false;
  const content = fs.readFileSync(envPath, 'utf-8');
  const match = content.match(/ANTHROPIC_API_KEY=(.+)/);
  return match && match[1].trim().length > 10 && !match[1].includes('your-key-here');
}

async function promptForApiKey() {
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'DeepDive — First Run Setup',
    message: 'Anthropic API key required',
    detail: 'DeepDive needs an Anthropic API key to function.\n\nYou can get one at console.anthropic.com.\n\nWould you like to enter it now?',
    buttons: ['Enter Key', 'Quit'],
    defaultId: 0,
  });

  if (result.response === 1) {
    app.quit();
    return false;
  }

  // Simple input dialog — Electron doesn't have a native text input dialog,
  // so we use the preload page for this.
  return true;
}

// ── Streamlit server ───────────────────────────────────────────────
function startStreamlit() {
  const appPath = getAppPath();
  const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

  console.log(`[DeepDive] Starting Streamlit from: ${appPath}`);

  streamlitProcess = spawn(pythonCmd, [
    '-m', 'streamlit', 'run', 'dashboard.py',
    '--server.port', String(STREAMLIT_PORT),
    '--server.headless', 'true',
    '--server.address', '127.0.0.1',
    '--browser.gatherUsageStats', 'false',
  ], {
    cwd: appPath,
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  streamlitProcess.stdout.on('data', (data) => {
    console.log(`[Streamlit] ${data.toString().trim()}`);
  });

  streamlitProcess.stderr.on('data', (data) => {
    console.log(`[Streamlit] ${data.toString().trim()}`);
  });

  streamlitProcess.on('close', (code) => {
    console.log(`[Streamlit] Process exited with code ${code}`);
    streamlitProcess = null;
  });

  streamlitProcess.on('error', (err) => {
    console.error(`[Streamlit] Failed to start: ${err.message}`);
    dialog.showErrorBox(
      'DeepDive — Error',
      `Could not start the analysis server.\n\nMake sure Python is installed and on your PATH.\n\nError: ${err.message}`
    );
  });
}

// ── Window ─────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'DeepDive',
    backgroundColor: '#0a0a12',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  // Remove default menu bar
  mainWindow.setMenuBarVisibility(false);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Splash / loading screen ────────────────────────────────────────
function showLoading() {
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        @import url('https://fonts.googleapis.com/css2?family=Permanent+Marker&family=Space+Mono&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          background: #0a0a12;
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100vh;
          overflow: hidden;
          position: relative;
        }
        body::after {
          content: '';
          position: fixed;
          inset: 0;
          background: repeating-linear-gradient(0deg, transparent 0px, transparent 2px, rgba(0,0,0,.06) 2px, rgba(0,0,0,.06) 4px);
          pointer-events: none;
        }
        .container { text-align: center; }
        .title {
          font-family: 'Permanent Marker', cursive;
          font-size: 4rem;
          color: #ff2d95;
          text-shadow: 0 0 30px rgba(255,45,149,.5), 0 0 80px rgba(255,45,149,.2);
          line-height: 1.1;
        }
        .subtitle {
          font-family: 'Space Mono', monospace;
          font-size: 0.78rem;
          letter-spacing: 0.15em;
          color: #00f0ff;
          text-shadow: 0 0 10px rgba(0,240,255,.4);
          text-transform: uppercase;
          margin-bottom: 0.5rem;
        }
        .status {
          font-family: 'Space Mono', monospace;
          font-size: 0.8rem;
          color: #39ff14;
          text-shadow: 0 0 8px rgba(57,255,20,.4);
          margin-top: 2rem;
          animation: pulse 1.5s ease-in-out infinite;
        }
        @keyframes pulse {
          0%, 100% { opacity: 0.5; }
          50% { opacity: 1; }
        }
        .orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(100px);
          animation: drift 18s ease-in-out infinite alternate;
        }
        .orb-1 {
          width: 400px; height: 400px;
          background: radial-gradient(circle, rgba(255,45,149,.15) 0%, transparent 70%);
          top: 10%; left: 15%;
        }
        .orb-2 {
          width: 350px; height: 350px;
          background: radial-gradient(circle, rgba(139,0,255,.12) 0%, transparent 70%);
          bottom: 10%; right: 15%;
          animation-delay: -9s;
        }
        @keyframes drift {
          0% { transform: translate(0,0) scale(1); }
          50% { transform: translate(30px,-20px) scale(1.08); }
          100% { transform: translate(-20px,30px) scale(.95); }
        }
      </style>
    </head>
    <body>
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="container">
        <p class="subtitle">multi-agent research & analysis</p>
        <h1 class="title">DEEPDIVE</h1>
        <p class="status">initializing agents...</p>
      </div>
    </body>
    </html>
  `)}`);
}

// ── App lifecycle ──────────────────────────────────────────────────
app.whenReady().then(async () => {
  createWindow();
  showLoading();

  // Check for API key
  if (!hasApiKey()) {
    const proceed = await promptForApiKey();
    if (!proceed) return;
  }

  // Check if Streamlit is already running (dev mode)
  const alreadyRunning = await isPortInUse(STREAMLIT_PORT);

  if (!alreadyRunning) {
    startStreamlit();
  } else {
    console.log('[DeepDive] Streamlit already running on port', STREAMLIT_PORT);
  }

  try {
    await waitForPort(STREAMLIT_PORT, 45000);
    console.log('[DeepDive] Streamlit is ready');
    mainWindow.loadURL(`http://127.0.0.1:${STREAMLIT_PORT}`);
  } catch (err) {
    dialog.showErrorBox(
      'DeepDive — Startup Error',
      'The analysis server did not start in time.\n\nCheck that Python and all dependencies are installed.\n\nRun: pip install -r requirements.txt'
    );
    app.quit();
  }
});

app.on('window-all-closed', () => {
  if (streamlitProcess) {
    console.log('[DeepDive] Killing Streamlit server...');
    streamlitProcess.kill();
    streamlitProcess = null;
  }
  app.quit();
});

app.on('before-quit', () => {
  if (streamlitProcess) {
    streamlitProcess.kill();
    streamlitProcess = null;
  }
});
