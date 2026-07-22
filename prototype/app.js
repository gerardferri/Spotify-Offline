/* YT-MP3 Studio PWA: all media remains in this browser's IndexedDB. */
const DB_NAME = 'ytmp3-studio-pwa'; const DB_VERSION = 1;
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
let db, tracks = [], activeTrack, currentUrl, playerCoverUrl, selectedTrack, sortNewest = true, toastTimer, coverUrls = [], jobsTimer, driveTimer, driveSnapshot = null;
let shuffleEnabled = false, repeatMode = 'off';
const audio = $('#audio');

function openDb() { return new Promise((resolve, reject) => { const request = indexedDB.open(DB_NAME, DB_VERSION); request.onupgradeneeded = () => { const database = request.result; const trackStore = database.createObjectStore('tracks', { keyPath: 'id' }); trackStore.createIndex('fingerprint', 'fingerprint', { unique: true }); trackStore.createIndex('createdAt', 'createdAt'); database.createObjectStore('playlists', { keyPath: 'id' }); const links = database.createObjectStore('playlistTracks', { keyPath: ['playlistId', 'trackId'] }); links.createIndex('playlistId', 'playlistId'); database.createObjectStore('settings', { keyPath: 'key' }); }; request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }); }
function tx(store, mode = 'readonly') { return db.transaction(store, mode).objectStore(store); }
function requestAsPromise(request) { return new Promise((resolve, reject) => { request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error); }); }
function all(store) { return requestAsPromise(tx(store).getAll()); }
function getSetting(key) { return requestAsPromise(tx('settings').get(key)).then(item => item?.value ?? ''); }
function setSetting(key, value) { return requestAsPromise(tx('settings', 'readwrite').put({ key, value })); }
function id() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; }
function formatBytes(bytes = 0) { if (!bytes) return '0 MB'; const units = ['B', 'KB', 'MB', 'GB']; const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3); return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`; }
function time(seconds = 0) { seconds = Number.isFinite(seconds) ? Math.floor(seconds) : 0; return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`; }
function escape(text = '') { const el = document.createElement('span'); el.textContent = text; return el.innerHTML; }
function showToast(text) { $('#toast').textContent = text; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 2800); }

async function digest(file) { const bytes = await file.arrayBuffer(); const hash = await crypto.subtle.digest('SHA-256', bytes); return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join(''); }
function syncSafeInt(bytes, offset) { return ((bytes[offset] & 0x7f) << 21) | ((bytes[offset + 1] & 0x7f) << 14) | ((bytes[offset + 2] & 0x7f) << 7) | (bytes[offset + 3] & 0x7f); }
function decodeText(data, encoding) { if (!data?.length) return ''; const label = encoding === 1 || encoding === 2 ? 'utf-16' : encoding === 3 ? 'utf-8' : 'iso-8859-1'; try { return new TextDecoder(label).decode(data).replace(/^\uFEFF/, '').replace(/\0/g, '').trim(); } catch { return ''; } }
function id3v2(buffer) { const bytes = new Uint8Array(buffer); const result = {}; if (String.fromCharCode(...bytes.slice(0, 3)) !== 'ID3') return result; const major = bytes[3], end = 10 + syncSafeInt(bytes, 6); let pos = 10; while (pos + 10 <= end && pos + 10 <= bytes.length) { const key = String.fromCharCode(...bytes.slice(pos, pos + 4)); const size = major === 4 ? syncSafeInt(bytes, pos + 4) : new DataView(buffer).getUint32(pos + 4); if (!key.trim() || size <= 0 || pos + 10 + size > bytes.length) break; const data = bytes.slice(pos + 10, pos + 10 + size); if (key === 'TIT2') result.title = decodeText(data.slice(1), data[0]); if (key === 'TPE1') result.artist = decodeText(data.slice(1), data[0]); if (key === 'TALB') result.album = decodeText(data.slice(1), data[0]); if (key === 'APIC') { let cursor = 1; while (cursor < data.length && data[cursor]) cursor++; const mime = new TextDecoder().decode(data.slice(1, cursor)) || 'image/jpeg'; cursor += 2; const descriptionEnd = data[0] === 1 || data[0] === 2 ? (() => { let p = cursor; while (p + 1 < data.length && (data[p] || data[p + 1])) p += 2; return p + 2; })() : (() => { let p = cursor; while (p < data.length && data[p]) p++; return p + 1; })(); if (descriptionEnd < data.length) result.cover = new Blob([data.slice(descriptionEnd)], { type: mime }); } pos += 10 + size; } return result; }
function fallbackName(name) { return name.replace(/\.[^.]+$/, '').replace(/[._-]+/g, ' ').trim(); }
async function importFiles(fileList) { const files = [...fileList].filter(file => file.type.startsWith('audio/') || /\.(mp3|m4a|aac|wav|ogg)$/i.test(file.name)); if (!files.length) return; let added = 0, duplicates = 0; for (const file of files) { try { const fingerprint = await digest(file); const existing = await requestAsPromise(tx('tracks').index('fingerprint').get(fingerprint)); if (existing) { duplicates++; continue; } const info = id3v2(await file.arrayBuffer()); const track = { id: id(), fingerprint, blob: file, cover: info.cover || null, title: info.title || fallbackName(file.name), artist: info.artist || 'Artista desconocido', album: info.album || '', createdAt: new Date().toISOString(), size: file.size, mime: file.type || 'audio/mpeg', favorite: false, duration: null }; await requestAsPromise(tx('tracks', 'readwrite').put(track)); added++; } catch (error) { console.error('No se pudo importar el archivo', error); } } await refresh(); showToast(`${added} pista${added === 1 ? '' : 's'} importada${added === 1 ? '' : 's'}${duplicates ? ` · ${duplicates} ya existían` : ''}`); $('#fileInput').value = ''; }
async function refresh() { tracks = await all('tracks'); tracks.sort((a, b) => sortNewest ? b.createdAt.localeCompare(a.createdAt) : a.title.localeCompare(b.title, 'es')); renderTracks(); await renderPlaylists(); updateStorage(); }
function cover(track) { if (!track.cover) return '♫'; const url = URL.createObjectURL(track.cover); coverUrls.push(url); return `<img src="${url}" alt="">`; }
function filteredTracks() { const query = $('#libraryFilter').value.trim().toLocaleLowerCase('es'); return tracks.filter(track => !query || `${track.title} ${track.artist} ${track.album}`.toLocaleLowerCase('es').includes(query)); }
function renderTracks() { coverUrls.forEach(URL.revokeObjectURL); coverUrls = []; const list = $('#trackList'), visible = filteredTracks(); $('#emptyState').hidden = tracks.length !== 0; $('#librarySummary').textContent = tracks.length ? `${tracks.length} pista${tracks.length === 1 ? '' : 's'} guardada${tracks.length === 1 ? '' : 's'} para escuchar sin conexión.` : 'Importa tus archivos de audio para empezar.'; list.innerHTML = visible.map(track => `<article class="track"><button class="cover play-track" data-id="${track.id}" aria-label="Reproducir ${escape(track.title)}">${cover(track)}</button><div class="track-main"><strong>${escape(track.title)}</strong><small>${escape(track.artist)}${track.album ? ` · ${escape(track.album)}` : ''}</small></div><div class="track-actions"><button class="play-track" data-id="${track.id}" aria-label="Reproducir">▶</button><button class="menu-track" data-id="${track.id}" aria-label="Opciones">⋯</button></div></article>`).join(''); $$('.play-track').forEach(button => button.onclick = () => play(button.dataset.id)); $$('.menu-track').forEach(button => button.onclick = () => openMenu(button.dataset.id)); }
async function renderPlaylists() { const playlists = await all('playlists'), links = await all('playlistTracks'); const driveFolders = driveSnapshot?.connected ? driveSnapshot.folders || [] : []; $('#emptyPlaylists').hidden = playlists.length + driveFolders.length !== 0; const localMarkup = playlists.sort((a,b) => a.createdAt.localeCompare(b.createdAt)).map(playlist => { const count = links.filter(link => link.playlistId === playlist.id).length; return `<button class="playlist" data-id="${playlist.id}"><span class="playlist-icon">≡</span><span><strong>${escape(playlist.name)}</strong><small>${count} canción${count === 1 ? '' : 'es'}</small></span></button>`; }).join(''); const driveMarkup = driveFolders.map(folder => `<button class="playlist drive-playlist" data-drive-folder-id="${escape(folder.id)}"><span class="playlist-icon drive-playlist-icon">D</span><span><strong>${escape(folder.name)}</strong><small>${Number(folder.track_count || 0)} canción${Number(folder.track_count || 0) === 1 ? '' : 'es'} · Google Drive</small></span><span class="remote-pill">Nube</span></button>`).join(''); $('#playlistList').innerHTML = localMarkup + driveMarkup; $$('.playlist[data-id]').forEach(button => button.onclick = () => openPlaylist(button.dataset.id)); $$('.drive-playlist').forEach(button => button.onclick = () => focusDriveFolder(button.dataset.driveFolderId)); }
async function play(trackId) {
  const track = tracks.find(item => item.id === trackId);
  if (!track) return;
  if (activeTrack?.id === trackId) {
    audio.paused ? audio.play() : audio.pause();
    return;
  }
  if (currentUrl) URL.revokeObjectURL(currentUrl);
  if (playerCoverUrl) URL.revokeObjectURL(playerCoverUrl);
  activeTrack = track;
  currentUrl = URL.createObjectURL(track.blob);
  playerCoverUrl = track.cover ? URL.createObjectURL(track.cover) : null;
  audio.src = currentUrl;
  $('#player').hidden = false;
  $('#playerTitle').textContent = track.title;
  $('#playerArtist').textContent = track.artist;
  $('#playerCover').innerHTML = playerCoverUrl ? `<img src="${playerCoverUrl}" alt="">` : '♫';
  document.title = `${track.title} · YT-MP3 Studio`;
  updateMediaSession();
  audio.play().catch(() => showToast('Toca reproducir para iniciar el audio.'));
}

function updateMediaSession() {
  if (!('mediaSession' in navigator) || !activeTrack) return;
  navigator.mediaSession.metadata = new MediaMetadata({ title: activeTrack.title, artist: activeTrack.artist, album: activeTrack.album || 'YT-MP3 Studio' });
  navigator.mediaSession.setActionHandler('play', () => audio.play());
  navigator.mediaSession.setActionHandler('pause', () => audio.pause());
  navigator.mediaSession.setActionHandler('nexttrack', () => next());
  navigator.mediaSession.setActionHandler('previoustrack', previous);
  navigator.mediaSession.setActionHandler('seekbackward', details => seekBy(-(details.seekOffset || 10)));
  navigator.mediaSession.setActionHandler('seekforward', details => seekBy(details.seekOffset || 10));
  navigator.mediaSession.setActionHandler('seekto', details => seekTo(details.seekTime));
}

function randomTrack() {
  if (tracks.length < 2) return tracks[0];
  const candidates = tracks.filter(track => track.id !== activeTrack?.id);
  return candidates[Math.floor(Math.random() * candidates.length)];
}

function next(fromEnded = false) {
  if (!activeTrack || !tracks.length) return;
  if (fromEnded && repeatMode === 'one') {
    audio.currentTime = 0;
    audio.play();
    return;
  }
  if (shuffleEnabled) {
    play(randomTrack().id);
    return;
  }
  const index = tracks.findIndex(track => track.id === activeTrack.id);
  const atEnd = index === tracks.length - 1;
  if (fromEnded && atEnd && repeatMode === 'off') {
    audio.currentTime = 0;
    updateProgress();
    return;
  }
  play(tracks[(index + 1) % tracks.length].id);
}

function previous() {
  if (!activeTrack || !tracks.length) return;
  if (audio.currentTime > 3) {
    seekTo(0);
    return;
  }
  if (shuffleEnabled) {
    play(randomTrack().id);
    return;
  }
  const index = tracks.findIndex(track => track.id === activeTrack.id);
  play(tracks[(index - 1 + tracks.length) % tracks.length].id);
}

function seekTo(seconds) {
  if (!Number.isFinite(seconds)) return;
  audio.currentTime = Math.max(0, Math.min(seconds, audio.duration || 0));
  updateProgress();
}

function seekBy(seconds) { seekTo(audio.currentTime + seconds); }

function updateProgress() {
  const progress = $('#progress');
  const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
  if (!progress.matches(':active')) progress.value = audio.currentTime;
  progress.style.setProperty('--progress', duration ? `${(audio.currentTime / duration) * 100}%` : '0%');
  $('#elapsed').textContent = time(audio.currentTime);
  $('#duration').textContent = time(duration);
}

function toggleShuffle() {
  shuffleEnabled = !shuffleEnabled;
  const button = $('#playerShuffle');
  button.classList.toggle('is-active', shuffleEnabled);
  button.setAttribute('aria-pressed', String(shuffleEnabled));
  button.setAttribute('aria-label', shuffleEnabled ? 'Desactivar reproducción aleatoria' : 'Activar reproducción aleatoria');
  button.title = shuffleEnabled ? 'Aleatorio activado' : 'Aleatorio';
}

function toggleRepeat() {
  repeatMode = repeatMode === 'off' ? 'all' : repeatMode === 'all' ? 'one' : 'off';
  const button = $('#playerRepeat');
  const enabled = repeatMode !== 'off';
  button.dataset.mode = repeatMode;
  button.classList.toggle('is-active', enabled);
  button.setAttribute('aria-pressed', String(enabled));
  button.setAttribute('aria-label', repeatMode === 'one' ? 'Repetir esta canción' : enabled ? 'Repetir todas las canciones' : 'Activar repetición');
  button.title = repeatMode === 'one' ? 'Repetir una' : enabled ? 'Repetir todo' : 'Repetir';
  $('#repeatCount').hidden = repeatMode !== 'one';
}
async function openMenu(trackId) { selectedTrack = tracks.find(track => track.id === trackId); if (!selectedTrack) return; $('#menuTrackTitle').textContent = selectedTrack.title; $('#favoriteAction').textContent = selectedTrack.favorite ? 'Quitar de favoritos' : 'Añadir a favoritos'; const playlists = await all('playlists'); $('#playlistSelect').innerHTML = playlists.length ? playlists.map(item => `<option value="${item.id}">${escape(item.name)}</option>`).join('') : '<option value="">Crea primero una playlist</option>'; $('#addToPlaylist').disabled = !playlists.length; $('#trackMenu').showModal(); }
async function addToPlaylist() { const playlistId = $('#playlistSelect').value; if (!playlistId || !selectedTrack) return; await requestAsPromise(tx('playlistTracks', 'readwrite').put({ playlistId, trackId: selectedTrack.id, addedAt: new Date().toISOString() })); $('#trackMenu').close(); await renderPlaylists(); showToast('Añadida a la playlist.'); }
async function toggleFavorite() { if (!selectedTrack) return; selectedTrack.favorite = !selectedTrack.favorite; await requestAsPromise(tx('tracks', 'readwrite').put(selectedTrack)); $('#trackMenu').close(); await refresh(); }
async function deleteTrack() { if (!selectedTrack || !confirm(`¿Eliminar “${selectedTrack.title}” de este iPhone?`)) return; const transaction = db.transaction(['tracks', 'playlistTracks'], 'readwrite'); transaction.objectStore('tracks').delete(selectedTrack.id); const links = await requestAsPromise(transaction.objectStore('playlistTracks').getAll()); links.filter(link => link.trackId === selectedTrack.id).forEach(link => transaction.objectStore('playlistTracks').delete([link.playlistId, link.trackId])); await new Promise((resolve, reject) => { transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error); }); $('#trackMenu').close(); if (activeTrack?.id === selectedTrack.id) { audio.pause(); if (currentUrl) URL.revokeObjectURL(currentUrl); if (playerCoverUrl) URL.revokeObjectURL(playerCoverUrl); currentUrl = null; playerCoverUrl = null; $('#player').hidden = true; activeTrack = null; document.title = 'YT-MP3 Studio · Biblioteca offline'; } await refresh(); showToast('Pista eliminada.'); }
async function openPlaylist(playlistId) { const playlists = await all('playlists'); const playlist = playlists.find(item => item.id === playlistId); const links = await all('playlistTracks'); const list = links.filter(link => link.playlistId === playlistId).map(link => tracks.find(track => track.id === link.trackId)).filter(Boolean); $('#playlistDialogTitle').textContent = playlist.name; $('#playlistTracks').innerHTML = list.length ? list.map(track => `<article class="track"><button class="cover play-track" data-id="${track.id}" aria-label="Reproducir ${escape(track.title)}">♫</button><div class="track-main"><strong>${escape(track.title)}</strong><small>${escape(track.artist)}</small></div><button class="play-track" data-id="${track.id}" aria-label="Reproducir ${escape(track.title)}">▶</button></article>`).join('') : '<p class="empty-state compact">Esta playlist está vacía.</p>'; $$('#playlistTracks .play-track').forEach(button => button.onclick = () => play(button.dataset.id)); $('#playlistDialog').showModal(); }
async function createPlaylist(event) { event.preventDefault(); const name = $('#playlistName').value.trim(); if (!name) return; await requestAsPromise(tx('playlists', 'readwrite').put({ id: id(), name, createdAt: new Date().toISOString() })); event.target.reset(); await renderPlaylists(); showToast('Playlist creada.'); }
async function exportBackup() { const library = await all('tracks'), playlists = await all('playlists'), links = await all('playlistTracks'); const backup = { version: 1, exportedAt: new Date().toISOString(), tracks: library.map(({ blob, cover, ...track }) => track), playlists, playlistTracks: links.map(link => ({ playlistId: link.playlistId, fingerprint: library.find(track => track.id === link.trackId)?.fingerprint })).filter(link => link.fingerprint) }; const url = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: 'application/json' })); const link = Object.assign(document.createElement('a'), { href: url, download: `ytmp3-studio-backup-${new Date().toISOString().slice(0,10)}.json` }); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); showToast('Copia exportada. Los audios no se incluyen.'); }
async function restoreBackup(file) { try { const backup = JSON.parse(await file.text()); if (backup.version !== 1 || !Array.isArray(backup.playlists)) throw new Error('Formato no válido'); const current = await all('tracks'); const byFingerprint = new Map(current.map(track => [track.fingerprint, track.id])); const playlistById = new Map(); for (const playlist of backup.playlists) { const newId = id(); playlistById.set(playlist.id, newId); await requestAsPromise(tx('playlists', 'readwrite').put({ id: newId, name: playlist.name, createdAt: playlist.createdAt || new Date().toISOString() })); } let matched = 0; for (const link of backup.playlistTracks || []) { const trackId = byFingerprint.get(link.fingerprint), playlistId = playlistById.get(link.playlistId); if (trackId && playlistId) { await requestAsPromise(tx('playlistTracks', 'readwrite').put({ playlistId, trackId, addedAt: new Date().toISOString() })); matched++; } } for (const saved of backup.tracks || []) { const existing = current.find(track => track.fingerprint === saved.fingerprint); if (existing && typeof saved.favorite === 'boolean') { existing.favorite = saved.favorite; await requestAsPromise(tx('tracks', 'readwrite').put(existing)); } } await refresh(); showToast(`Copia restaurada: ${matched} pistas asociadas.`); } catch (error) { showToast('No se pudo leer esa copia de seguridad.'); console.error(error); } finally { $('#restoreInput').value = ''; } }
async function updateStorage() { const ownBytes = tracks.reduce((total, track) => total + (track.size || 0), 0); let suffix = `Música guardada: ${formatBytes(ownBytes)}.`; if (navigator.storage?.estimate) { const estimate = await navigator.storage.estimate(); suffix += ` Espacio del sitio: ${formatBytes(estimate.usage)} de ${formatBytes(estimate.quota)}.`; } $('#storageUsage').textContent = suffix; }
async function clearLibrary() { if (!confirm('¿Borrar todas las pistas, playlists y datos guardados en este iPhone? Esta acción no se puede deshacer.')) return; db.close(); await new Promise((resolve, reject) => { const request = indexedDB.deleteDatabase(DB_NAME); request.onsuccess = resolve; request.onerror = () => reject(request.error); }); db = await openDb(); activeTrack = null; audio.pause(); if (currentUrl) URL.revokeObjectURL(currentUrl); if (playerCoverUrl) URL.revokeObjectURL(playerCoverUrl); currentUrl = null; playerCoverUrl = null; $('#player').hidden = true; document.title = 'YT-MP3 Studio · Biblioteca offline'; await refresh(); showToast('Biblioteca borrada.'); }

function navigate(pageName) { $$('.nav-item').forEach(item => { const active = item.dataset.page === pageName; item.classList.toggle('is-active', active); if (active) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); }); $$('.page').forEach(page => page.classList.toggle('is-visible', page.id === `page-${pageName}`)); if (pageName === 'downloads') loadJobs(); if (pageName === 'library' && driveSnapshot) loadDriveStatus({ quiet: true }); window.scrollTo({ top: 0, behavior: 'smooth' }); }
function isLocalDesktopApp() { return ['localhost', '127.0.0.1'].includes(location.hostname); }
async function serverConfig() { if (isLocalDesktopApp()) return { url: location.origin, token: '' }; return { url: String(await getSetting('serverUrl')).replace(/\/+$/, ''), token: String(await getSetting('serverToken')) }; }
async function api(path, options = {}) { const config = await serverConfig(); if (!config.url || (!config.token && !isLocalDesktopApp())) throw new Error('Configura primero la dirección y la clave del PC.'); if (!config.url.startsWith('https://') && !/^http:\/\/(localhost|127\.0\.0\.1)(:|$)/.test(config.url)) throw new Error('El servidor necesita una dirección HTTPS.'); const response = await fetch(`${config.url}${path}`, { ...options, cache: 'no-store', headers: { ...(config.token ? { Authorization: `Bearer ${config.token}` } : {}), ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) } }); if (!response.ok) { let message = `El PC respondió con error ${response.status}.`; try { message = (await response.json()).error?.message || message; } catch {} throw new Error(message); } return response; }

function driveErrorHint(error) {
  const message = String(error?.message || 'No se ha podido conectar con Google Drive.');
  if (/configura primero|servidor/i.test(message)) return 'Conecta esta web con la aplicación del PC desde Ajustes. Google Drive se vincula y sincroniza de forma segura en el PC.';
  if (/failed to fetch|load failed|network|conexión|connection/i.test(message)) return 'El PC no está disponible. Tu música guardada sigue funcionando offline; vuelve a intentarlo cuando el PC esté conectado.';
  return message;
}
function setDriveState(state, message = '') {
  const hub = $('#driveHub');
  hub.dataset.state = state;
  hub.setAttribute('aria-busy', String(state === 'loading' || state === 'connecting' || state === 'syncing'));
  $('#driveLoading').hidden = !['loading', 'connecting', 'syncing'].includes(state);
  $('#driveDisconnected').hidden = state !== 'disconnected';
  $('#driveConnected').hidden = state !== 'connected';
  $('#driveError').hidden = state !== 'error';
  const labels = { loading: 'Comprobando…', connecting: 'Conectando…', syncing: 'Sincronizando…', connected: 'Conectado', disconnected: 'Sin conectar', error: 'Sin conexión' };
  $('#driveStatus').querySelector('span').textContent = labels[state] || state;
  if (state === 'connecting') { $('#driveLoading strong').textContent = 'Abriendo Google'; $('#driveLoading small').textContent = 'Completa la autorización para vincular tu biblioteca.'; }
  else if (state === 'syncing') { $('#driveLoading strong').textContent = 'Sincronizando tu música'; $('#driveLoading small').textContent = 'Estamos leyendo los cambios de tus carpetas de Drive.'; }
  else { $('#driveLoading strong').textContent = 'Comprobando Google Drive'; $('#driveLoading small').textContent = 'Tu biblioteca local seguirá disponible.'; }
  if (message) $('#driveErrorMessage').textContent = message;
}
function formatDriveDate(value) {
  if (!value) return 'Todavía no se ha sincronizado.';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Última sincronización disponible.';
  return `Última sincronización: ${new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(date)}`;
}
function renderDriveFolders(folders = []) {
  const list = $('#driveFolderList');
  $('#driveFolderEmpty').hidden = folders.length !== 0;
  $('#driveFolderTotal').textContent = `${folders.length} carpeta${folders.length === 1 ? '' : 's'}`;
  list.innerHTML = folders.map(folder => {
    const count = Number(folder.track_count || 0);
    const tracks = Array.isArray(folder.tracks) ? folder.tracks : [];
    const trackMarkup = tracks.length ? `<div class="drive-remote-tracks">${tracks.map(track => { const trackId = track.file_id || track.id; return `<div><span>${escape(track.title || track.name || 'Canción')}</span>${trackId ? `<button class="quiet-button save-drive-track" data-track-id="${escape(trackId)}" data-title="${escape(track.title || track.name || 'cancion')}">Guardar en iPhone</button>` : ''}</div>`; }).join('')}</div>` : '';
    return `<article class="drive-folder" data-drive-folder="${escape(folder.id)}" tabindex="0" role="button" aria-label="Abrir ${escape(folder.name || 'carpeta de Drive')}"><span class="drive-folder-icon" aria-hidden="true"></span><div><strong>${escape(folder.name || 'Carpeta sin nombre')}</strong><small>${count} canción${count === 1 ? '' : 'es'} · Toca para verlas</small>${trackMarkup}</div><span class="drive-folder-count">${count}</span></article>`;
  }).join('');
  $$('.drive-folder').forEach(folder => { folder.onclick = event => { if (!event.target.closest('button')) loadDriveFolderTracks(folder.dataset.driveFolder); }; folder.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); loadDriveFolderTracks(folder.dataset.driveFolder); } }; });
  $$('.save-drive-track').forEach(button => button.onclick = event => { event.stopPropagation(); saveDriveTrack(button); });
}
async function loadDriveFolderTracks(folderId) {
  const folder = driveSnapshot?.folders.find(item => item.id === folderId);
  if (!folder || folder.loading) return;
  folder.loading = true;
  try {
    const response = await api(`/api/drive/folders/${encodeURIComponent(folderId)}/tracks`);
    const payload = await response.json();
    folder.tracks = Array.isArray(payload.tracks) ? payload.tracks : [];
    renderDriveFolders(driveSnapshot.folders);
  } catch (error) { showToast(driveErrorHint(error)); }
  finally { folder.loading = false; }
}
async function saveDriveTrack(button) {
  button.disabled = true;
  button.textContent = 'Copiando…';
  try {
    const response = await api(`/api/drive/files/${encodeURIComponent(button.dataset.trackId)}/audio`);
    const blob = await response.blob();
    const safeTitle = (button.dataset.title || 'cancion').replace(/[\\/:*?"<>|]/g, '_');
    await importFiles([new File([blob], safeTitle, { type: blob.type || 'audio/mpeg' })]);
    button.textContent = 'Guardada';
  } catch (error) { showToast(error.message); button.disabled = false; button.textContent = 'Guardar en iPhone'; }
}
async function applyDrivePayload(payload) {
  const drive = payload?.drive || payload || {};
  driveSnapshot = { connected: Boolean(drive.connected), configured: drive.configured !== false, account_email: drive.account_email || '', folder_name: drive.folder_name || 'YT-MP3 Studio', last_sync_at: drive.last_sync_at || null, syncing: Boolean(drive.syncing), folders: Array.isArray(drive.folders) ? drive.folders : [], track_count: Number(drive.track_count || 0), error: drive.error || null };
  if (driveSnapshot.error) { setDriveState('error', driveSnapshot.error); return; }
  if (!driveSnapshot.configured) { setDriveState('error', 'Falta preparar Google Drive en el PC. Añade google-client-secret.json siguiendo la guía de configuración y vuelve a intentarlo.'); renderDriveFolders([]); return; }
  if (!driveSnapshot.connected) { setDriveState('disconnected'); renderDriveFolders([]); await renderPlaylists(); return; }
  const email = driveSnapshot.account_email;
  $('#driveAvatar').textContent = (email || 'G').slice(0, 1).toUpperCase();
  $('#driveAccountName').textContent = driveSnapshot.folder_name;
  $('#driveAccountEmail').textContent = email || 'Google Drive conectado en el PC';
  $('#driveSyncSummary').textContent = `${driveSnapshot.track_count} canción${driveSnapshot.track_count === 1 ? '' : 'es'} en ${driveSnapshot.folders.length} carpeta${driveSnapshot.folders.length === 1 ? '' : 's'}`;
  $('#driveLastSync').textContent = formatDriveDate(driveSnapshot.last_sync_at);
  renderDriveFolders(driveSnapshot.folders);
  setDriveState(driveSnapshot.syncing ? 'syncing' : 'connected');
  if (driveSnapshot.syncing) setTimeout(() => loadDriveStatus({ quiet: true }), 2000);
  await renderPlaylists();
}
let driveRequestActive = false;
async function loadDriveStatus({ quiet = false, autoSync = false } = {}) {
  if (driveRequestActive) return;
  driveRequestActive = true;
  let shouldAutoSync = false;
  if (!quiet || !driveSnapshot) setDriveState('loading');
  try { const response = await api('/api/drive/status'); await applyDrivePayload(await response.json()); shouldAutoSync = autoSync && driveSnapshot?.connected && !driveSnapshot.syncing; }
  catch (error) { setDriveState('error', driveErrorHint(error)); }
  finally { driveRequestActive = false; }
  if (shouldAutoSync) await syncDrive({ quiet: true });
}
async function connectDrive() {
  setDriveState('connecting');
  $('#driveConnect').disabled = true;
  try {
    const response = await api('/api/drive/connect', { method: 'POST' });
    const payload = await response.json();
    if (!payload.authorization_url) throw new Error('El PC no ha podido iniciar la autorización de Google.');
    location.assign(payload.authorization_url);
  } catch (error) { setDriveState('error', driveErrorHint(error)); $('#driveConnect').disabled = false; }
}
async function syncDrive({ quiet = false } = {}) {
  if (driveRequestActive) return;
  driveRequestActive = true;
  setDriveState('syncing');
  $('#driveSync').disabled = true;
  try { const response = await api('/api/drive/sync', { method: 'POST' }); await applyDrivePayload(await response.json()); if (!quiet) showToast('Google Drive está actualizado.'); }
  catch (error) { setDriveState('error', driveErrorHint(error)); }
  finally { driveRequestActive = false; $('#driveSync').disabled = false; }
}
async function disconnectDrive() {
  if (!confirm('¿Desconectar Google Drive? Las canciones guardadas en este dispositivo no se borrarán.')) return;
  setDriveState('connecting');
  try { const response = await api('/api/drive/disconnect', { method: 'POST' }); await applyDrivePayload(await response.json()); showToast('Google Drive desconectado.'); }
  catch (error) { setDriveState('error', driveErrorHint(error)); }
}
function focusDriveFolder(folderId) {
  navigate('library');
  requestAnimationFrame(() => { const folder = $$('.drive-folder').find(item => item.dataset.driveFolder === folderId); (folder || $('#driveHub')).scrollIntoView({ behavior: 'smooth', block: 'center' }); folder?.classList.add('is-highlighted'); setTimeout(() => folder?.classList.remove('is-highlighted'), 1600); });
}
async function updateServerBanner(test = false) { const config = await serverConfig(); const banner = $('#serverBanner'); if (isLocalDesktopApp()) { banner.classList.add('online'); $('#serverStatus').textContent = 'Aplicación web local'; $('#serverHint').textContent = 'Conectada solo a este PC'; if (test) $('#connectionResult').textContent = 'Aplicación web local conectada correctamente.'; return true; } if (!config.url || !config.token) { banner.classList.remove('online'); $('#serverStatus').textContent = 'Servidor sin configurar'; $('#serverHint').textContent = 'Introduce la dirección y la clave en Ajustes.'; return false; } if (!test) { $('#serverStatus').textContent = 'Servidor configurado'; $('#serverHint').textContent = config.url; return true; } $('#serverStatus').textContent = 'Conectando con el PC…'; try { const response = await api('/api/health'); const result = await response.json(); banner.classList.add('online'); $('#serverStatus').textContent = 'PC conectado'; $('#serverHint').textContent = result.name || config.url; $('#connectionResult').textContent = `Conectado correctamente a ${config.url}`; return true; } catch (error) { banner.classList.remove('online'); $('#serverStatus').textContent = 'PC no disponible'; $('#serverHint').textContent = error.message; $('#connectionResult').textContent = error.message; return false; } }
async function saveServerConfig() { const url = $('#serverUrl').value.trim().replace(/\/+$/, ''), token = $('#serverToken').value.trim(); if (!url || !token) { showToast('Completa la dirección y la clave del PC.'); return; } await Promise.all([setSetting('serverUrl', url), setSetting('serverToken', token)]); const ok = await updateServerBanner(true); showToast(ok ? 'Servidor conectado.' : 'No se pudo conectar con el PC.'); }
async function searchRemote(event) { event.preventDefault(); $('#searchEmpty').hidden = true; $('#searchResults').innerHTML = '<p class="loading">Buscando desde el PC…</p>'; try { const response = await api(`/api/search?q=${encodeURIComponent($('#remoteQuery').value.trim())}&limit=12`); const payload = await response.json(); renderSearchResults(payload.results || []); } catch (error) { $('#searchResults').innerHTML = `<p class="error-card">${escape(error.message)}</p>`; } }
function renderSearchResults(results) { $('#searchEmpty').hidden = results.length !== 0; $('#searchResults').innerHTML = results.length ? results.map(result => `<article class="remote-result"><div class="result-art">${result.thumbnail_url ? `<img src="${escape(result.thumbnail_url)}" alt="" loading="lazy">` : '♫'}</div><div><strong>${escape(result.title)}</strong><small>${escape(result.channel || 'Canal desconocido')}${result.duration_seconds ? ` · ${time(result.duration_seconds)}` : ''}</small></div><button class="primary enqueue-result" data-video-id="${escape(result.video_id)}">Descargar</button></article>`).join('') : '<p class="error-card">No se encontraron resultados.</p>'; $$('.enqueue-result').forEach(button => button.onclick = () => enqueueRemote(button)); }
async function enqueueRemote(button) { button.disabled = true; button.textContent = 'Enviando…'; try { await api('/api/jobs', { method: 'POST', body: JSON.stringify({ video_id: button.dataset.videoId, quality_kbps: 192 }) }); showToast('Descarga enviada al PC.'); navigate('downloads'); } catch (error) { showToast(error.message); button.disabled = false; button.textContent = 'Descargar'; } }
const jobLabels = { queued: 'En espera', resolving: 'Preparando', downloading: 'Descargando', converting: 'Convirtiendo', completed: 'Lista', failed: 'Error', interrupted: 'Interrumpida', paused: 'Pausada', cancelled: 'Cancelada' };
async function loadJobs() { const config = await serverConfig(); if (!config.url || (!config.token && !isLocalDesktopApp())) { $('#jobList').innerHTML = '<p class="error-card">Configura el servidor en Ajustes.</p>'; $('#jobsEmpty').hidden = true; return; } try { const response = await api('/api/jobs'); const payload = await response.json(); renderJobs(payload.jobs || []); } catch (error) { $('#jobList').innerHTML = `<p class="error-card">${escape(error.message)}</p>`; $('#jobsEmpty').hidden = true; } }
function renderJobs(jobs) { $('#jobsEmpty').hidden = jobs.length !== 0; $('#jobList').innerHTML = jobs.map(job => { const progress = Math.max(0, Math.min(100, Number(job.progress_percent || (job.state === 'completed' ? 100 : 0)))); const action = job.state === 'completed' && job.track_id ? `<button class="primary save-remote" data-track-id="${job.track_id}" data-title="${escape(job.title)}">Guardar en iPhone</button>` : ''; return `<article class="remote-job"><div class="job-head"><div><strong>${escape(job.title || 'Descarga')}</strong><small>${escape(job.channel || '')}</small></div><span class="job-state state-${escape(job.state)}">${jobLabels[job.state] || escape(job.state)}</span></div><div class="job-progress"><i style="width:${progress}%"></i></div>${job.error_message ? `<p class="job-error">${escape(job.error_message)}</p>` : ''}${action}</article>`; }).join(''); $$('.save-remote').forEach(button => button.onclick = () => saveRemoteTrack(button)); }
async function saveRemoteTrack(button) { button.disabled = true; button.textContent = 'Copiando…'; try { const response = await api(`/api/tracks/${encodeURIComponent(button.dataset.trackId)}/audio`); const blob = await response.blob(); const safeTitle = (button.dataset.title || 'cancion').replace(/[\\/:*?"<>|]/g, '_'); const file = new File([blob], `${safeTitle}.mp3`, { type: blob.type || 'audio/mpeg' }); await importFiles([file]); button.textContent = 'Guardada'; navigate('library'); } catch (error) { showToast(error.message); button.disabled = false; button.textContent = 'Guardar en iPhone'; } }

function syncPlayerClearance() {
  const nav = $('.bottom-nav');
  document.documentElement.style.setProperty('--bottom-nav-height', `${Math.ceil(nav.getBoundingClientRect().height)}px`);
}

function bind() {
  syncPlayerClearance();
  if ('ResizeObserver' in window) new ResizeObserver(syncPlayerClearance).observe($('.bottom-nav'));
  else window.addEventListener('resize', syncPlayerClearance);
  $$('.nav-item').forEach(button => button.onclick = () => navigate(button.dataset.page));
  $('#importButton').onclick = () => $('#fileInput').click();
  $('#emptyImportButton').onclick = $('#emptyImportButton2').onclick = () => $('#fileInput').click();
  $('#fileInput').onchange = event => importFiles(event.target.files);
  $('#libraryFilter').oninput = renderTracks;
  $('#sortButton').onclick = () => { sortNewest = !sortNewest; $('#sortButton').textContent = sortNewest ? 'Recientes' : 'A–Z'; $('#sortButton').setAttribute('aria-pressed', String(sortNewest)); refresh(); };
  $('#newPlaylistForm').onsubmit = createPlaylist;
  $('#backupButton').onclick = exportBackup;
  $('#restoreInput').onchange = event => event.target.files[0] && restoreBackup(event.target.files[0]);
  $('#addToPlaylist').onclick = addToPlaylist;
  $('#trackMenu').addEventListener('close', () => { const value = $('#trackMenu').returnValue; if (value === 'favorite') toggleFavorite(); if (value === 'delete') deleteTrack(); });

  $('#playerPlay').onclick = () => audio.paused ? audio.play() : audio.pause();
  $('#playerPrevious').onclick = previous;
  $('#playerNext').onclick = () => next();
  $('#playerShuffle').onclick = toggleShuffle;
  $('#playerRepeat').onclick = toggleRepeat;
  $('#progress').oninput = event => seekTo(Number(event.target.value));
  $('#player').onkeydown = event => {
    if (event.target.matches('input, button')) return;
    if (event.code === 'Space') { event.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
    if (event.code === 'ArrowLeft') { event.preventDefault(); seekBy(-5); }
    if (event.code === 'ArrowRight') { event.preventDefault(); seekBy(5); }
  };

  audio.onplay = () => { $('#playerPlayIcon').className = 'control-icon icon-pause'; $('#playerPlay').setAttribute('aria-label', 'Pausar'); $('#playerPlay').title = 'Pausar'; };
  audio.onpause = () => { $('#playerPlayIcon').className = 'control-icon icon-play'; $('#playerPlay').setAttribute('aria-label', 'Reproducir'); $('#playerPlay').title = 'Reproducir'; };
  audio.ontimeupdate = () => {
    updateProgress();
    if ('mediaSession' in navigator && Number.isFinite(audio.duration) && audio.duration > 0) navigator.mediaSession.setPositionState({ duration: audio.duration, playbackRate: audio.playbackRate, position: Math.min(audio.currentTime, audio.duration) });
  };
  audio.onloadedmetadata = () => { const progress = $('#progress'); progress.max = audio.duration || 0; progress.value = 0; updateProgress(); };
  audio.onended = () => next(true);

  $('#remoteSearchForm').onsubmit = searchRemote;
  $('#refreshJobs').onclick = loadJobs;
  $('#openServerSettings').onclick = () => navigate('settings');
  $('#driveConnect').onclick = connectDrive;
  $('#driveSync').onclick = syncDrive;
  $('#driveDisconnect').onclick = disconnectDrive;
  $('#driveRetry').onclick = () => loadDriveStatus();
  $('#driveOpenSettings').onclick = () => navigate('settings');
  $('#openDriveLibrary').onclick = () => { navigate('library'); requestAnimationFrame(() => $('#driveHub').scrollIntoView({ behavior: 'smooth', block: 'start' })); };
  $('#saveServer').onclick = saveServerConfig;
  $('#toggleToken').onclick = () => { const input = $('#serverToken'); input.type = input.type === 'password' ? 'text' : 'password'; $('#toggleToken').textContent = input.type === 'password' ? 'Mostrar clave' : 'Ocultar clave'; };
  $('#requestPersistence').onclick = async () => { const granted = await navigator.storage?.persist?.(); showToast(granted ? 'Safari protegerá los datos cuando sea posible.' : 'Safari no pudo garantizar el almacenamiento.'); };
  $('#clearLibrary').onclick = clearLibrary;
}
async function init() { db = await openDb(); bind(); await refresh(); $('#serverUrl').value = isLocalDesktopApp() ? location.origin : await getSetting('serverUrl'); $('#serverToken').value = await getSetting('serverToken'); await updateServerBanner(false); const driveCallback = new URLSearchParams(location.search).get('drive') === 'connected'; await loadDriveStatus({ autoSync: true }); if (driveCallback) { const cleanUrl = new URL(location.href); cleanUrl.searchParams.delete('drive'); history.replaceState({}, '', `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`); showToast('Google Drive conectado.'); } jobsTimer = setInterval(() => { if ($('#page-downloads').classList.contains('is-visible') && !document.hidden) loadJobs(); }, 4000); driveTimer = setInterval(() => { if (!document.hidden && driveSnapshot?.connected) syncDrive({ quiet: true }); }, 300000); if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js', { updateViaCache: 'none' }).catch(console.error); }
init().catch(error => { console.error(error); showToast('No se pudo abrir la biblioteca local.'); });
