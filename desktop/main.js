// Hypertube desktop: starts Jackett and the back on this machine, then shows the site in a window.
const { app, BrowserWindow, Menu, shell, dialog } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");

// where the parts are: next to the app when it is installed, in stage/ when it is run from the sources
const parts = app.isPackaged ? process.resourcesPath : path.join(__dirname, "stage");
const data = app.getPath("userData"); // ~/Library/Application Support/Hypertube
const children = [];

function freePort(preferred) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => freePort(0).then(resolve));
    server.listen(preferred || 0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function waitFor(url, label, seconds = 90) {
  return new Promise((resolve, reject) => {
    const until = Date.now() + seconds * 1000;
    const ask = () =>
      http
        .get(url, (res) => {
          res.resume();
          // Jackett answers 302 while it sets its cookie: that is "up"
          res.statusCode < 500 ? resolve() : retry();
        })
        .on("error", retry);
    const retry = () => (Date.now() > until ? reject(new Error(`${label} did not start`)) : setTimeout(ask, 500));
    ask();
  });
}

function run(command, args, options) {
  const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"], ...options });
  const log = fs.createWriteStream(path.join(data, `${path.basename(command)}.log`), { flags: "a" });
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  children.push(child);
  return child;
}

function stopAll() {
  for (const child of children) child.kill();
  children.length = 0;
}

async function start() {
  fs.mkdirSync(data, { recursive: true });
  const jackettPort = await freePort(0);
  const backPort = await freePort(0);
  const torrentPort = await freePort(6881);

  const jackettData = path.join(data, "jackett");
  fs.mkdirSync(jackettData, { recursive: true });
  // -z: this machine only (by default Jackett listens on every interface, with no password)
  run(path.join(parts, "jackett", "jackett"), ["-d", jackettData, "-p", String(jackettPort), "-z", "--NoUpdates", "--NoRestart"], { cwd: path.join(parts, "jackett") });

  const env = {
    ...process.env,
    PORT: String(backPort),
    DATABASE_URL: `sqlite:///${path.join(data, "hypertube.db")}`,
    DOWNLOAD_DIR: path.join(data, "cache"),
    LIBRARY_DIR: process.env.LIBRARY_DIR || path.join(os.homedir(), "Desktop", "hypertube"),
    FRONTEND_DIR: path.join(parts, "frontend"),
    JACKETT_URL: `http://127.0.0.1:${jackettPort}`,
    JACKETT_CONFIG: path.join(jackettData, "ServerConfig.json"),
    FFMPEG: path.join(parts, "bin", "ffmpeg"),
    FFPROBE: path.join(parts, "bin", "ffprobe"),
    TORRENT_PORT: String(torrentPort),
  };
  const back = run(path.join(parts, "backend", "hypertube-backend"), [], { env });
  back.on("exit", (code) => {
    if (code) dialog.showErrorBox("Hypertube", `The back stopped (code ${code}). See ${path.join(data, "hypertube-backend.log")}.`);
  });

  await waitFor(`http://127.0.0.1:${backPort}/api/auth/me`, "the back");
  const win = new BrowserWindow({ width: 1280, height: 820, backgroundColor: "#141414", title: "Hypertube" });
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url); // a link out of the app opens in the browser
    return { action: "deny" };
  });
  win.loadURL(`http://127.0.0.1:${backPort}/`);
}

if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => BrowserWindow.getAllWindows()[0]?.focus());

app.whenReady().then(() => {
  Menu.setApplicationMenu(Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" }]));
  start().catch((e) => {
    dialog.showErrorBox("Hypertube", String(e.message || e));
    app.quit();
  });
});
app.on("window-all-closed", () => app.quit());
app.on("will-quit", stopAll);
