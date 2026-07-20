const menuButton = document.querySelector('.menu-toggle');
const sidebar = document.querySelector('.sidebar');
const navLinks = [...document.querySelectorAll('.sidebar nav a')];
const toast = document.querySelector('#toast');

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 1800);
}

menuButton?.addEventListener('click', () => {
  const open = sidebar.classList.toggle('open');
  menuButton.setAttribute('aria-expanded', String(open));
});

navLinks.forEach(link => link.addEventListener('click', () => {
  sidebar.classList.remove('open');
  menuButton?.setAttribute('aria-expanded', 'false');
}));

const sectionObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    navLinks.forEach(link => link.classList.toggle('active', link.hash === `#${entry.target.id}`));
  });
}, { rootMargin: '-25% 0px -65% 0px' });
document.querySelectorAll('[data-section]').forEach(section => sectionObserver.observe(section));

const daily = document.querySelector('#daily');
const workflow = document.querySelector('#workflow');
const dailyOut = document.querySelector('#dailyOut');
const creditsOut = document.querySelector('#creditsOut');
const monthlyOut = document.querySelector('#monthlyOut');
const creditRate = document.querySelector('#creditRate');
const currency = document.querySelector('#currency');
const moneyOut = document.querySelector('#moneyOut');

function updateCalculator() {
  const count = Number(daily.value);
  const credits = Number(workflow.value) * count;
  const monthlyCredits = credits * 30;
  const rate = Number(creditRate.value);
  dailyOut.value = count;
  creditsOut.textContent = `${credits.toLocaleString()} credits`;
  monthlyOut.textContent = `${monthlyCredits.toLocaleString()} credits / 30 days`;
  moneyOut.textContent = rate > 0
    ? `${currency.value}${(credits * rate).toLocaleString(undefined, { maximumFractionDigits: 2 })} / day · ${currency.value}${(monthlyCredits * rate).toLocaleString(undefined, { maximumFractionDigits: 2 })} / 30 days`
    : 'Add a credit rate for currency cost';
  localStorage.setItem('ugc-cost-settings', JSON.stringify({ count, rate: creditRate.value, currency: currency.value, workflow: workflow.value }));
}

try {
  const saved = JSON.parse(localStorage.getItem('ugc-cost-settings'));
  if (saved) {
    daily.value = saved.count || 10;
    creditRate.value = saved.rate || '';
    currency.value = saved.currency || '₹';
    workflow.value = saved.workflow || '30';
  }
} catch {}
[daily, workflow, creditRate, currency].forEach(control => control.addEventListener('input', updateCalculator));
updateCalculator();

const connectSheet = document.querySelector('#connectSheet');
const openSheet = document.querySelector('#openSheet');
const sheetStatus = document.querySelector('#sheetStatus');
const defaultCostSheetUrl = 'https://docs.google.com/spreadsheets/d/1pwKUz7le_H1XCs39XjHrisueV7JgGiotsfHTXAbiB5s/edit?gid=1676287141#gid=1676287141';

function setSheetUrl(url) {
  if (!url) return;
  openSheet.href = url;
  openSheet.hidden = false;
  sheetStatus.textContent = 'Connected';
  connectSheet.textContent = 'Change link';
}
setSheetUrl(localStorage.getItem('ugc-cost-sheet-url') || defaultCostSheetUrl);
connectSheet.addEventListener('click', () => {
  const current = localStorage.getItem('ugc-cost-sheet-url') || defaultCostSheetUrl;
  const url = window.prompt('Paste the AI Cost Sheet URL', current);
  if (!url) return;
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error();
    localStorage.setItem('ugc-cost-sheet-url', parsed.href);
    setSheetUrl(parsed.href);
    showToast('AI Cost Sheet connected');
  } catch {
    showToast('Use a valid http or https URL');
  }
});

const mediaLibrary = {
  pm: {
    label: 'PM Tool · real self-serve outputs',
    title: 'Product modelling outputs',
    items: [
      { title: '01 · Downloads sequence', path: 'assets/web-videos/pm/01.mp4', poster: 'assets/videos/pm-downloads/01.jpg' },
      { title: '02 · Downloads sequence', path: 'assets/web-videos/pm/02.mp4', poster: 'assets/videos/pm-downloads/02.jpg' },
      { title: '03 · Downloads sequence', path: 'assets/web-videos/pm/03.mp4', poster: 'assets/videos/pm-downloads/03.jpg' },
      { title: 'Downloads · 137971_V2 (1)', path: 'assets/web-videos/pm/04-137971-v2.mp4', poster: 'assets/videos/pm-downloads/04-137971-v2.jpg' },
      { title: 'Downloads · 204540_V1 (1)', path: 'assets/web-videos/pm/05-204540-v1.mp4', poster: 'assets/videos/pm-downloads/05-204540-v1.jpg' },
      { title: 'Downloads · 5', path: 'assets/web-videos/pm/06.mp4', poster: 'assets/videos/pm-downloads/06.jpg' },
      { title: 'Downloads · 6', path: 'assets/web-videos/pm/07.mp4', poster: 'assets/videos/pm-downloads/07.jpg' },
      { title: 'Downloads · one more', path: 'assets/web-videos/pm/08-one-more.mp4', poster: 'assets/videos/pm-downloads/08-one-more.jpg' },
      { title: 'Golden Hour Field · PID 137971', path: 'assets/web-videos/selfserve/golden-hour-field-137971.mp4', poster: 'assets/web-videos/selfserve/golden-hour-field-137971.jpg' },
      { title: 'Poolside · PID 137971', path: 'assets/web-videos/selfserve/poolside-137971.mp4', poster: 'assets/web-videos/selfserve/poolside-137971.jpg' },
      { title: 'Beach · PID 204540 · possible duplicate', path: 'assets/web-videos/selfserve/beach-204540.mp4', poster: 'assets/web-videos/selfserve/beach-204540.jpg', duplicate: true },
      { title: 'Staircase · PID 207370', path: 'assets/web-videos/selfserve/staircase-207370.mp4', poster: 'assets/web-videos/selfserve/staircase-207370.jpg' },
      { title: 'Boutique · PID 137974', path: 'assets/web-videos/selfserve/boutique-137974.mp4', poster: 'assets/web-videos/selfserve/boutique-137974.jpg' }
    ]
  },
  th: {
    label: 'TH Tool · stitched and voiced finals',
    title: 'Talking-head outputs',
    items: [
      { title: '01 · Downloads sequence', path: 'assets/web-videos/th/01.mp4', poster: 'assets/videos/th-downloads/01.jpg' },
      { title: '02 · Downloads sequence', path: 'assets/web-videos/th/02.mp4', poster: 'assets/videos/th-downloads/02.jpg' },
      { title: '03 · Downloads sequence', path: 'assets/web-videos/th/03.mp4', poster: 'assets/videos/th-downloads/03.jpg' },
      { title: '04 · Downloads sequence', path: 'assets/web-videos/th/04.mp4', poster: 'assets/videos/th-downloads/04.jpg' },
      { title: '05 · Downloads sequence', path: 'assets/web-videos/th/05.mp4', poster: 'assets/videos/th-downloads/05.jpg' }
    ]
  },
  editing: {
    label: 'Manny · product modelling and video editing',
    title: 'Production workflow recording',
    items: [
      { title: 'Tool-to-edit workflow · screen recording', path: 'assets/manny-work/product-modelling-video-editing/web/screen-recording.mp4', poster: 'assets/manny-work/product-modelling-video-editing/web/screen-recording.jpg' }
    ]
  },
  lottie: {
    label: 'Manny · Lottie systems',
    title: 'Lottie motion library',
    items: [
      { title: 'Lottie 01', path: 'assets/manny-work/lottie-systems/web/1.mp4', poster: 'assets/manny-work/lottie-systems/web/1.jpg' },
      { title: 'Lottie 02', path: 'assets/manny-work/lottie-systems/web/2.mp4', poster: 'assets/manny-work/lottie-systems/web/2.jpg' },
      { title: 'Lottie 03', path: 'assets/manny-work/lottie-systems/web/3.mp4', poster: 'assets/manny-work/lottie-systems/web/3.jpg' },
      { title: 'Lottie 04', path: 'assets/manny-work/lottie-systems/web/4.mp4', poster: 'assets/manny-work/lottie-systems/web/4.jpg' },
      { title: 'Lottie 05', path: 'assets/manny-work/lottie-systems/web/5.mp4', poster: 'assets/manny-work/lottie-systems/web/5.jpg' },
      { title: 'Lottie 06', path: 'assets/manny-work/lottie-systems/web/6.mp4', poster: 'assets/manny-work/lottie-systems/web/6.jpg' },
      { title: 'Lottie 07', path: 'assets/manny-work/lottie-systems/web/7.mp4', poster: 'assets/manny-work/lottie-systems/web/7.jpg' }
    ]
  },
  apps: {
    label: 'Manny · app videos',
    title: 'App-video library',
    items: [
      { title: 'TBYB · captioned', path: 'assets/manny-work/app-videos/web/TBYB_with-caption.mp4', poster: 'assets/manny-work/app-videos/web/TBYB_with-caption.jpg' },
      { title: 'Eye test at home · captioned', path: 'assets/manny-work/app-videos/web/eye-test-ahome_captions.mp4', poster: 'assets/manny-work/app-videos/web/eye-test-ahome_captions.jpg' },
      { title: 'RFR · captions v3.2', path: 'assets/manny-work/app-videos/web/rfr_captions2_v3.2.mp4', poster: 'assets/manny-work/app-videos/web/rfr_captions2_v3.2.jpg' }
    ]
  }
};

const mediaDialog = document.querySelector('#mediaDialog');
const libraryPlayer = document.querySelector('#libraryPlayer');
const libraryPath = document.querySelector('#libraryPath');
const mediaList = document.querySelector('#mediaList');

function selectMedia(item, button) {
  libraryPlayer.pause();
  libraryPlayer.poster = item.poster || '';
  libraryPlayer.src = item.path;
  libraryPlayer.load();
  libraryPath.textContent = item.path.replace('../', '');
  [...mediaList.children].forEach(child => child.classList.toggle('active', child === button));
}

function openMediaLibrary(type) {
  const library = mediaLibrary[type];
  document.querySelector('#mediaType').textContent = library.label;
  document.querySelector('#mediaTitle').textContent = library.title;
  mediaList.replaceChildren();
  library.items.forEach((item, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `media-item${item.duplicate ? ' duplicate' : ''}`;
    button.setAttribute('role', 'listitem');
    button.innerHTML = `<img src="${item.poster}" alt=""><span><strong>${item.title}</strong><small>${item.path.replace('../', '')}</small></span>`;
    button.addEventListener('click', () => selectMedia(item, button));
    mediaList.append(button);
    if (index === 0) selectMedia(item, button);
  });
  mediaDialog.showModal();
}
document.querySelectorAll('[data-library]').forEach(button => button.addEventListener('click', () => openMediaLibrary(button.dataset.library)));

const readinessEvidence = {
  'video-model-testing': {
    title: 'Video model testing', pmScore: '88%', thScore: '82%',
    pmReason: 'PM has production prompt libraries for Seedance 2.0 and Kling 3.0, three shot variants per engine, parallel take generation and real outputs across indoor/outdoor scenes. It is close to repeatable, but the full PID/character/scene matrix is not yet automated.',
    thReason: 'TH routes hook, wearing and pose roles across Seedance and Kling and has completed end-to-end builds. More engines and a broader character/product test matrix still need comparable scoring.',
    pmEvidence: '_shots_for(model, take_idx)\n_SEEDANCE_VARIANTS = [V1, V2, V3]\n_KLING_VARIANTS = [V1, V2, V3]\nsubmit all → poll all',
    thEvidence: 'hook → seedance_2_0\nwearing → kling3_0\npose → kling3_0\n4 B-rolls → kling3_0',
    gap: 'A benchmark runner that scores the same PID, character and prompt across every candidate model, records cost/latency/QC, and promotes the winner automatically.'
  },
  'model-pickup': {
    title: 'Model pickup', pmScore: '80%', thScore: '74%',
    pmReason: 'The operator can explicitly choose Seedance or Kling, and each choice changes media arity, prompt format and cost. Routing rules exist, but selection is still manual rather than based on measured output quality.',
    thReason: 'Role-based routing is deterministic and proven, but it is a fixed table. It does not yet evaluate alternative engines per cut or fall back based on live cost, queue state or QC.',
    pmEvidence: 'if model == "seedance_2_0":\n  medias = [still or anchor]\nelse:\n  medias = [still or anchor, *product_refs]',
    thEvidence: 'route = {\n  "hook": "seedance_2_0",\n  "wearing": "kling3_0",\n  "pose": "kling3_0"\n}',
    gap: 'A policy layer that consumes benchmark results, budget, queue health and QC confidence before selecting or escalating an engine.'
  },
  clothing: {
    title: 'Clothing', pmScore: '72%', thScore: '70%',
    pmReason: 'The PM remix path exposes top/bottom styles and colours and carries those choices into prompt construction. Product-modelling still relies primarily on character anchors and scene styling rather than trained wardrobe identity.',
    thReason: 'TH has a reusable clothing matrix, UI dropdowns, outfit phrase construction and try-on still generation. Generalization across bodies, fabrics and movement remains dependent on foundation models.',
    pmEvidence: 'top_style + top_color\nbottom_style + bottom_color\n→ outfit prompt\n→ try-on still',
    thEvidence: 'clothing.json\noutfit_phrase(top_style, top_color,\n               bottom_style, bottom_color)\n→ KIT_PROMPT → TRYON_PROMPT',
    gap: 'A versioned wardrobe dataset, trained LoRAs, garment identity scoring and failure handling for occlusion, fabric physics and body-shape changes.'
  },
  scripting: {
    title: 'Scripting', pmScore: '55%', thScore: '86%',
    pmReason: 'PM uses strong deterministic scene preambles and numbered shot lists, but it does not yet have a rich narrative scripting layer or approval workflow comparable to TH.',
    thReason: 'TH supports a Claude-written Pattern 1, a cheaper local Pattern 2, linting, editable approval, cut packing and semantic role assignment. Additional validated formats are the main missing surface.',
    pmEvidence: 'preamble + _shots_for(model, take_idx)\n→ fixed visual shot grammar\n→ no narrative approval gate',
    thEvidence: 'generate_script() | generate_auto_script()\n→ lint_script()\n→ split_cuts()\n→ assign_roles()\n→ Gate 1 edit + approve',
    gap: 'More proven script patterns, outcome tracking by hook/lane, systematic brand-voice controls and open-model replacement for the creative setup path.'
  },
  stitching: {
    title: 'Stitching', pmScore: '62%', thScore: '90%',
    pmReason: 'PM produces organized individual takes and includes a hard-cut remix path, but the main product-modelling experience is still oriented around selecting outputs rather than building a finished multi-layer ad.',
    thReason: 'TH has silence removal, continuous A-roll, timed B-roll overlay, voice replacement, forced alignment and final export. The remaining work is resilience across more cut counts and production presets.',
    pmEvidence: '_concat_hardcut(clip_paths, out_path)\nrun_remix(...)\nindividual takes + QC sheets',
    thEvidence: 'silencedetect → keep ranges → A-roll base\nB-roll windows @ 3s / every 3s\noverlay composition → STS voice → alignment',
    gap: 'PM needs a first-class assembly grammar; TH needs broader regression tests, export presets, queue recovery and automated alerts before unattended scale.'
  }
};

const justificationDialog = document.querySelector('#justificationDialog');
document.querySelectorAll('[data-justify]').forEach(button => button.addEventListener('click', () => {
  const item = readinessEvidence[button.dataset.justify];
  document.querySelector('#justificationTitle').textContent = item.title;
  document.querySelector('#pmScore').textContent = item.pmScore;
  document.querySelector('#thScore').textContent = item.thScore;
  document.querySelector('#pmReason').textContent = item.pmReason;
  document.querySelector('#thReason').textContent = item.thReason;
  document.querySelector('#pmEvidence').textContent = item.pmEvidence;
  document.querySelector('#thEvidence').textContent = item.thEvidence;
  document.querySelector('#scoreGap').textContent = item.gap;
  justificationDialog.showModal();
}));

document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    showToast('Folder path copied');
  } catch {
    showToast(button.dataset.copy);
  }
}));

document.querySelector('#replayMotion')?.addEventListener('click', () => {
  const demo = document.querySelector('.motion-demo');
  const clone = demo.cloneNode(true);
  demo.replaceWith(clone);
  showToast('Motion replayed');
});

const reviewDialog = document.querySelector('#reviewDialog');
const reviewForm = document.querySelector('#reviewForm');
const reviewSection = document.querySelector('#reviewSection');
const reviewNote = document.querySelector('#reviewNote');
const notesList = document.querySelector('#notesList');
const reviewCount = document.querySelector('#reviewCount');
const notesKey = 'ugc-site-review-notes';

function getNotes() {
  try { return JSON.parse(localStorage.getItem(notesKey)) || []; } catch { return []; }
}

function saveNotes(notes) {
  localStorage.setItem(notesKey, JSON.stringify(notes));
  renderNotes();
}

function renderNotes() {
  const notes = getNotes();
  reviewCount.textContent = notes.length;
  notesList.replaceChildren();
  if (!notes.length) {
    notesList.innerHTML = '<p class="empty-notes">No review notes yet. Add feedback or a question for Bella.</p>';
    return;
  }
  notes.forEach(note => {
    const row = document.createElement('article');
    row.className = 'review-note';
    const section = document.createElement('strong');
    section.textContent = note.section;
    const copy = document.createElement('p');
    copy.textContent = note.text;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = 'Remove';
    remove.addEventListener('click', () => saveNotes(getNotes().filter(item => item.id !== note.id)));
    row.append(section, copy, remove);
    notesList.append(row);
  });
}

document.querySelectorAll('[data-review-open]').forEach(button => button.addEventListener('click', () => {
  reviewSection.value = button.dataset.reviewSection || 'Overall feedback';
  reviewDialog.showModal();
  setTimeout(() => reviewNote.focus(), 50);
}));

reviewForm.addEventListener('submit', event => {
  event.preventDefault();
  const notes = getNotes();
  notes.push({ id: crypto.randomUUID(), section: reviewSection.value, text: reviewNote.value.trim(), createdAt: new Date().toISOString() });
  saveNotes(notes);
  reviewNote.value = '';
  showToast('Review note saved');
});

document.querySelector('#clearNotes').addEventListener('click', () => {
  if (!getNotes().length || !window.confirm('Clear every saved review note?')) return;
  saveNotes([]);
  showToast('Review notes cleared');
});

document.querySelector('#exportNotes').addEventListener('click', () => {
  const payload = { project: "Manny's UGC Systems", exportedAt: new Date().toISOString(), notes: getNotes() };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ugc-systems-review-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
  showToast('Review JSON exported');
});

document.querySelectorAll('[data-dialog-close]').forEach(button => button.addEventListener('click', () => {
  const dialog = button.closest('dialog');
  if (dialog === mediaDialog) libraryPlayer.pause();
  dialog.close();
}));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  if (dialog === mediaDialog) libraryPlayer.pause();
  dialog.close();
}));

renderNotes();
