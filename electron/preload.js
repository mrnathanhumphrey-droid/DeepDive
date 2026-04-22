// Preload script — minimal, just bridges context isolation.
// No node APIs exposed to the renderer for security.
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('deepdive', {
  platform: process.platform,
  version: require('./package.json').version,
});
