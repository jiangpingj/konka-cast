/* KonkaCast 控制台前端逻辑 */
'use strict';

const api = {
  async get(path) {
    const r = await fetch(path);
    return await r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    return await r.json();
  },
};

const $ = (sel) => document.querySelector(sel);
const el = {
  devList: $('#dev-list'),
  devDetail: $('#dev-detail'),
  btnScan: $('#btn-scan'),
  badgeIp: $('#badge-ip'),
  badgeFf: $('#badge-ffmpeg'),
  badgeMirror: $('#badge-mirror'),
  ffmpegMissing: $('#ffmpeg-missing'),
  btnFetchFf: $('#btn-fetch-ffmpeg'),
  fetchStatus: $('#fetch-status'),
  fetchProgress: $('#fetch-progress'),
  mEncoder: $('#m-encoder'),
  mFps: $('#m-fps'),
  mBitrate: $('#m-bitrate'),
  mAudio: $('#m-audio'),
  audioHint: $('#audio-hint'),
  btnMirrorStart: $('#btn-mirror-start'),
  btnMirrorStop: $('#btn-mirror-stop'),
  mirrorUrl: $('#mirror-url'),
  dirInput: $('#dir-input'),
  fileList: $('#file-list'),
  dropzone: $('#dropzone'),
  urlInput: $('#url-input'),
  logUl: $('#log'),
  seek: $('#seek'),
  posText: $('#pos-text'),
  durText: $('#dur-text'),
  volume: $('#volume'),
  volText: $('#vol-text'),
  statePill: $('#state-pill'),
};

let state = { selectedIp: null, duration: 0, seeking: false, curDir: null, logIds: 0 };
let audioDevicesDone = false;

/* ---------------- 通用 UI ---------------- */
function toast(msg, kind = 'ok') {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.textContent = msg;
  $('#toasts').appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity .25s';
    node.style.opacity = '0';
    setTimeout(() => node.remove(), 250);
  }, 3600);
}

function setBadge(node, label, strong, cls) {
  node.querySelector('span').textContent = label;
  node.querySelector('strong').textContent = strong;
  node.className = `badge ${cls || ''}`;
}

function toSeconds(hms) {
  if (!hms || hms === '--:--:--' || hms === 'NOT_IMPLEMENTED') return 0;
  const p = (hms || '').split(':').map(Number);
  if (p.length !== 3 || p.some(isNaN)) return 0;
  return p[0] * 3600 + p[1] * 60 + p[2];
}
function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/* ---------------- 设备 ---------------- */
function renderDevices(devices) {
  if (!devices || !devices.length) {
    el.devList.innerHTML = '<li class="empty">没找到设备。确认电视已开机、DLNA 开关已打开，且与电脑在同一网段</li>';
    el.devDetail.hidden = true;
    return;
  }
  el.devList.innerHTML = '';
  devices.forEach((d) => {
    const li = document.createElement('li');
    li.className = d.selected ? 'active' : '';
    li.innerHTML = `
      <span class="dev-name"></span>
      <span class="dev-meta">
        <span class="ip"></span>
        <span class="vendor"></span>
      </span>`;
    li.querySelector('.dev-name').textContent = d.name;
    li.querySelector('.ip').textContent = d.ip;
    li.querySelector('.vendor').textContent = d.vendor || d.model || '';
    // 用 location 作为唯一标识。同一 IP 上可能有多个接收端，
    // 传 IP 会让后台挑不中想要的那个。
    li.addEventListener('click', () => selectDevice(d.key || d.ip));
    el.devList.appendChild(li);
  });
}

function renderDeviceDetail(d) {
  if (!d) { el.devDetail.hidden = true; return; }
  el.devDetail.hidden = false;
  el.devDetail.innerHTML = '';
  const lines = [
    `型号：${d.model || '—'}`,
    `厂商：${d.vendor || '—'}`,
    `服务：${(d.services || []).join('、') || '—'}`,
  ];
  lines.forEach((t) => {
    const p = document.createElement('div');
    p.textContent = t;
    el.devDetail.appendChild(p);
  });
}

async function selectDevice(ident) {
  const res = await api.post('/api/select', { ip: ident, key: ident });
  if (res.ok) {
    toast('已切换接收端');
    await refresh();
  } else {
    toast(res.error || '选中失败', true);
  }
}

/* ---------------- 状态刷新 ---------------- */
async function refresh() {
  try {
    const s = await api.get('/api/status');
    let devices = s.devices || [];
    if (!devices.length && lastDevices.length) devices = lastDevices;
    lastDevices = devices;
    renderDevices(devices);
    renderDeviceDetail(s.selected);
    setBadge(el.badgeIp, '本机 IP', s.local_ip, 'ok');

    // ffmpeg
    const ff = s.ffmpeg || {};
    if (ff.ok) {
      setBadge(el.badgeFf, 'ffmpeg', ff.nvenc ? '已就绪 NVENC' : '已就绪', 'ok');
      el.ffmpegMissing.hidden = true;
      if (!audioDevicesDone) fillAudioDevices(ff.audio_devices || []);
    } else {
      setBadge(el.badgeFf, 'ffmpeg', '未安装', 'bad');
      el.ffmpegMissing.hidden = false;
    }

    // 镜像
    el.btnMirrorStart.disabled = s.mirror.running;
    el.btnMirrorStop.disabled = !s.mirror.running;
    el.mirrorUrl.textContent = s.mirror.running ? s.mirror.url : '';
    if (s.mirror.running) {
      setBadge(el.badgeMirror, '镜像', '运行中', 'live');
    } else {
      setBadge(el.badgeMirror, '镜像', '未启动', '');
    }

    // 播放状态
    const pb = s.playback || {};
    const st = pb.state || 'UNKNOWN';
    const pill = el.statePill;
    pill.textContent = { PLAYING: '播放中', PAUSED_PLAYBACK: '已暂停', STOPPED: '已停止',
                         TRANSITIONING: '连接中', NO_MEDIA_PRESENT: '无媒体' }[st] || st;
    pill.className = 'state-pill ' + (st === 'PLAYING' ? 'playing'
      : st === 'PAUSED_PLAYBACK' ? 'paused' : '');
    state.duration = toSeconds(pb.track_duration);
    el.durText.textContent = state.duration ? fmtTime(state.duration) : '--:--';
    const pos = toSeconds(pb.rel_time);
    el.posText.textContent = pos || state.duration ? fmtTime(pos) : '--:--';
    if (!state.seeking) {
      el.seek.max = String(state.duration || 100);
      el.seek.value = String(pos);
    }
    if (pb.volume !== null && pb.volume !== undefined) {
      el.volume.value = String(pb.volume);
      el.volText.textContent = pb.volume;
    }

    renderLog(s.notes || []);
    if (state.curDir === null) state.curDir = null;
    return s;
  } catch (e) {
    toast('与控制台通信失败：' + e.message, 'err');
  }
}

let lastDevices = [];
async function deviceList() {
  try {
    const r = await api.get('/api/devices');
    lastDevices = r.devices || [];
    return lastDevices;
  } catch { return lastDevices; }
}
function markSelected(s) {
  const picked = (s.selected || {}).key || (s.selected || {}).ip;
  return (lastDevices || []).map((d) => ({
    ...d,
    selected: picked != null && (d.key || d.ip) === picked,
  }));
}

/* ---------------- 日志 ---------------- */
let lastLogLen = -1;
function renderLog(notes) {
  if (!notes) return;
  if (notes.length === lastLogLen) return;
  lastLogLen = notes.length;
  el.logUl.innerHTML = '';
  notes.slice(-60).forEach((n) => {
    const li = document.createElement('li');
    li.innerHTML = `<span class="t">${n.t}</span><span class="lv-${n.level}"></span>`;
    li.children[1].textContent = n.text;
    el.logUl.appendChild(li);
  });
  el.logUl.scrollTop = el.logUl.scrollHeight;
}

/* ---------------- 音频设备 ---------------- */
function fillAudioDevices(devs) {
  audioDevicesDone = true;
  el.mAudio.innerHTML = '<option value="">不采集声音</option>';
  const prefer = devs.find((d) => /virtual|立体声混音|stereo mix|loopback|what u hear/i.test(d));
  devs.forEach((d) => {
    const o = document.createElement('option');
    o.value = d;
    o.textContent = d.length > 42 ? d.slice(0, 42) + '…' : d;
    el.mAudio.appendChild(o);
  });
  if (prefer) {
    el.mAudio.value = prefer;
    el.audioHint.textContent = `已自动选择「${prefer}」。若电视没声音，试试在 Windows 声音设置里启用「立体声混音」。`;
  } else if (devs.length) {
    el.audioHint.textContent = '没检测到虚拟声卡/立体声混音。想带声音投屏，可在 Windows 声音设置里启用「立体声混音」，或安装 VB-CABLE。';
  } else {
    el.audioHint.textContent = '没有可用的音频捕获设备，镜像将不带声音。';
  }
}

/* ---------------- 文件浏览 ---------------- */
async function browse(path) {
  const res = await api.get('/api/browse' + (path ? '?path=' + encodeURIComponent(path) : ''));
  if (!res.ok) {
    toast(res.error || '目录打不开', 'err');
    return;
  }
  state.curDir = res.path;
  el.dirInput.value = res.path;
  el.fileList.innerHTML = '';
  const entries = res.entries || [];
  if (!entries.length) {
    el.fileList.innerHTML = '<li class="file-empty">这个文件夹里没有可播放的文件</li>';
    return;
  }
  if (res.parent) {
    const li = document.createElement('li');
    li.innerHTML = '<span class="f-icon dir">DIR</span><span class="f-name">… 返回上级</span>';
    li.addEventListener('click', () => browse(res.parent));
    el.fileList.appendChild(li);
  }
  entries.forEach((f) => {
    const li = document.createElement('li');
    const icon = { dir: 'DIR', video: 'VID', music: 'AUD', photo: 'IMG' }[f.type === 'dir' ? 'dir' : f.kind] || 'FILE';
    li.innerHTML = `<span class="f-icon ${f.type === 'dir' ? 'dir' : f.kind}">${icon}</span>
      <span class="f-name"></span>
      <span class="f-size">${f.size || ''}</span>`;
    li.querySelector('.f-name').textContent = f.name;
    li.addEventListener('click', () => {
      if (f.type === 'dir') browse(f.path);
      else castFile(f.path);
    });
    el.fileList.appendChild(li);
  });
}

async function castFile(path) {
  const res = await api.post('/api/cast_file', { path });
  if (res.ok) toast(`已推送「${res.title}」`);
  else toast('推送失败：' + (res.error || '未知错误'), 'err');
  refresh();
}

/* ---------------- 拖拽上传 ---------------- */
function setupDropzone() {
  const dz = el.dropzone;
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  ['dragenter', 'dragover'].forEach((t) => dz.addEventListener(t, (e) => {
    stop(e); dz.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach((t) => dz.addEventListener(t, (e) => {
    stop(e); dz.classList.remove('over');
  }));
  dz.addEventListener('drop', async (e) => {
    const files = Array.from(e.dataTransfer.files || []);
    for (const f of files) {
      await uploadAndCast(f);
    }
  });
  // 阻止整页默认行为
  ['dragover', 'drop'].forEach((t) => document.addEventListener(t, (e) => e.preventDefault()));
}

async function uploadAndCast(file) {
  toast(`正在上传「${file.name}」…`);
  try {
    const r = await fetch('/api/upload?name=' + encodeURIComponent(file.name), {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
    const res = await r.json();
    if (res.ok) toast(`已推送「${res.title}」`);
    else toast('上传投屏失败：' + (res.error || '未知错误'), 'err');
  } catch (e) {
    toast('上传失败：' + e.message, 'err');
  }
  refresh();
}

/* ---------------- 事件绑定 ---------------- */
function bind() {
  el.btnScan.addEventListener('click', async () => {
    el.btnScan.disabled = true;
    el.btnScan.textContent = '扫描中…';
    const res = await api.post('/api/scan', { timeout: 3.5 });
    lastDevices = res.devices || [];
    renderDevices(lastDevices);
    el.btnScan.disabled = false;
    el.btnScan.textContent = '扫描';
    toast(res.devices && res.devices.length
      ? `找到 ${res.devices.length} 台设备`
      : '没找到设备', res.devices && res.devices.length ? 'ok' : 'err');
    refresh();
  });

  el.btnMirrorStart.addEventListener('click', async () => {
    el.btnMirrorStart.disabled = true;
    el.btnMirrorStart.textContent = '启动中…';
    const res = await api.post('/api/mirror/start', {
      fps: Number(el.mFps.value),
      bitrate: Number(el.mBitrate.value),
      encoder: el.mEncoder.value,
      audio_device: el.mAudio.value || null,
      scale: true,
    });
    el.btnMirrorStart.disabled = false;
    el.btnMirrorStart.textContent = '开始镜像';
    if (res.ok) toast('镜像已启动，电视应该马上出画面', 'ok');
    else toast('启动失败：' + (res.error || '未知错误'), 'err');
    refresh();
  });

  el.btnMirrorStop.addEventListener('click', async () => {
    const res = await api.post('/api/mirror/stop');
    toast(res.ok ? '已停止镜像' : '停止失败', res.ok ? 'ok' : 'err');
    refresh();
  });

  document.querySelectorAll('.btn-ctl').forEach((b) => {
    b.addEventListener('click', async () => {
      const res = await api.post('/api/control', { action: b.dataset.act });
      if (!res.ok) toast('控制失败：' + (res.error || ''), 'err');
      refresh();
    });
  });

  el.seek.addEventListener('change', async () => {
    state.seeking = false;
    await api.post('/api/control', { action: 'seek', value: Number(el.seek.value) });
    refresh();
  });
  el.seek.addEventListener('input', () => {
    state.seeking = true;
    el.posText.textContent = fmtTime(Number(el.seek.value));
  });

  el.volume.addEventListener('change', async () => {
    const res = await api.post('/api/control', { action: 'volume', value: Number(el.volume.value) });
    if (!res.ok) toast('音量设置失败（电视可能不支持）', 'err');
  });
  el.volume.addEventListener('input', () => {
    el.volText.textContent = el.volume.value;
  });

  $('#btn-mute').addEventListener('click', async () => {
    await api.post('/api/control', { action: 'mute', value: true });
    refresh();
  });

  $('#btn-dir-go').addEventListener('click', () => browse(el.dirInput.value.trim()));
  $('#btn-dir-up').addEventListener('click', () => browse(state.curDir ? parentOf(state.curDir) : ''));
  $('#btn-dir-home').addEventListener('click', () => browse(''));
  $('#btn-cast-url').addEventListener('click', async () => {
    const url = el.urlInput.value.trim();
    if (!url) return;
    const res = await api.post('/api/cast_url', { url });
    toast(res.ok ? '已推送' : '推送失败：' + (res.error || ''), res.ok ? 'ok' : 'err');
    refresh();
  });

  $('#btn-log-clear').addEventListener('click', () => { lastLogLen = -1; el.logUl.innerHTML = ''; });

  el.btnFetchFf.addEventListener('click', async () => {
    el.btnFetchFf.disabled = true;
    el.fetchProgress.hidden = false;
    await api.post('/api/ffmpeg/fetch');
    pollFetch();
  });

  setupDropzone();
}

function parentOf(p) {
  return p.split(/[\\/]/).slice(0, -1).join('\\') || p;
}

let fetchTimer = null;
function pollFetch() {
  if (fetchTimer) return;
  fetchTimer = setInterval(async () => {
    const r = await api.get('/api/ffmpeg/fetch-status');
    const s = r.state || {};
    el.fetchStatus.textContent = `${s.stage || ''} ${s.percent || 0}% ${s.message || ''}`.trim();
    el.fetchProgress.firstElementChild.style.width = (s.percent || 0) + '%';
    if (s.done) {
      clearInterval(fetchTimer);
      fetchTimer = null;
      el.btnFetchFf.disabled = false;
      if (s.ok) {
        await api.post('/api/ffmpeg/refresh', {});
        toast('ffmpeg 安装完成', 'ok');
        el.ffmpegMissing.hidden = true;
      } else {
        toast('自动下载失败，请手动安装 ffmpeg', 'err');
      }
      refresh();
    }
  }, 1200);
}

/* ---------------- 启动 ---------------- */
(async function boot() {
  bind();
  const s = await refresh();
  await browse('');
  setInterval(refresh, 2500);
})();
