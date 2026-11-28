export default function ({data, parentElement, setStateValue}) {
  const panel = parentElement.querySelector(".capture");
  const tr = (zh, en) => data.lang === "en" ? en : zh;
  const camera = panel.querySelector(".camera-file");
  const album = panel.querySelector(".album-file");
  const note = panel.querySelector("[role=status]");
  const storageKey = "sc6117.capture." + data.device;
  const buttons = Array.from(panel.querySelectorAll("button"));
  buttons[0].textContent = tr("拍下这餐", "Take photo");
  buttons[1].textContent = tr("从相册选", "Choose photo");
  function busy(value) { buttons.forEach(button => button.disabled = value); }
  function pending() {
    try { return JSON.parse(localStorage.getItem(storageKey)); }
    catch { return null; }
  }
  function send(record) {
    if (panel.dataset.sent === record.id) return;
    busy(true);
    panel.dataset.sent = record.id;
    setStateValue("capture", record);
  }
  const saved = pending();
  if (data.ack && saved?.id === data.ack) {
    try { localStorage.removeItem(storageKey); } catch { /* storage restricted */ }
  } else if (saved) {
    note.textContent = tr("正在同步刚拍的餐。", "Syncing your meal photo.");
    send(saved);
  }
  if (data.ack && panel.dataset.sent === data.ack) {
    busy(false);
    note.textContent = "";
  }

  async function selectPhoto(event) {
    const file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    let objectUrl;
    try {
      busy(true);
      note.textContent = tr("正在保存照片…", "Saving photo…");
      objectUrl = URL.createObjectURL(file);
      const photo = new Image();
      photo.src = objectUrl;
      await photo.decode();
      const canvas = document.createElement("canvas");
      const scale = Math.min(1, 1152 / Math.max(photo.width, photo.height));
      canvas.width = Math.max(1, Math.round(photo.width * scale));
      canvas.height = Math.max(1, Math.round(photo.height * scale));
      const context = canvas.getContext("2d");
      context.fillStyle = "white";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(photo, 0, 0, canvas.width, canvas.height);
      let jpeg = canvas.toDataURL("image/jpeg", 0.78).split(",")[1];
      if (jpeg.length > 240000) jpeg = canvas.toDataURL("image/jpeg", 0.53).split(",")[1];
      const uuid = crypto.randomUUID?.() || "10000000-1000-4000-8000-100000000000".replace(/[018]/g,
        ch => (Number(ch) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(ch) / 4).toString(16));
      const record = {id: uuid, device: data.device,
        captured_at: new Date().toISOString(), jpeg};
      try {
        localStorage.setItem(storageKey, JSON.stringify(record));
        note.textContent = tr("照片已保存在此浏览器，可以锁屏。", "Photo saved in this browser. You can lock your phone.");
      } catch { note.textContent = tr("正在同步，请等页面显示待确认。", "Syncing. Wait for the draft before closing."); }
      send(record);
    } catch {
      busy(false);
      note.textContent = tr("这张图片无法读取，请选 JPG 或 PNG，或重新拍一张。", "Could not read this image. Choose a JPG or PNG, or take another photo.");
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    }
  }
  buttons[0].onclick = () => camera.click();
  buttons[1].onclick = () => album.click();
  camera.onchange = selectPhoto;
  album.onchange = selectPhoto;
}
