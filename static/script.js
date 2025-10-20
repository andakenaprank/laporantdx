let currentStep = 1;

// 🔹 Tampilkan step tertentu
function showStep(step) {
  const steps = document.querySelectorAll(".form-step");
  steps.forEach((el, index) => {
    if (index === step - 1) {
      el.classList.add("active");
      el.querySelectorAll("[data-req='true']").forEach(input => input.required = true);
    } else {
      el.classList.remove("active");
      el.querySelectorAll("[data-req='true']").forEach(input => input.required = false);
    }
  });
  updateProgress(step);
}

// 🔹 Navigasi step
function nextStep() { if (validateStep(currentStep)) { currentStep++; showStep(currentStep); } }
function prevStep() { currentStep--; showStep(currentStep); }

// 🔹 Validasi field wajib
function validateStep(step) {
  const currentStepDiv = document.querySelector(`#step-${step}`);
  const inputs = currentStepDiv.querySelectorAll("[data-req='true']");
  for (let input of inputs) {
    if (!input.value || !input.value.trim()) {
      input.focus();
      alert("Harap isi semua field sebelum lanjut!");
      return false;
    }
  }
  return true;
}

// 🔹 Load daftar petugas dari database
async function loadPetugas() {
  try {
    const res = await fetch("/api/petugas", { cache: "no-store" });
    const data = await res.json();

    // kelompokkan berdasarkan jenis
    const grouped = {};
    data.forEach(p => {
      const j = (p.jenis || "").trim();
      if (!grouped[j]) grouped[j] = [];
      grouped[j].push(p);
    });

    function fillSelect(selectId, jenis) {
      const select = document.getElementById(selectId);
      if (!select) return;
      select.innerHTML = "<option value=''>-- Pilih --</option>";
      (grouped[jenis] || []).forEach(p => {
        select.innerHTML += `<option value="${p.nama}">${p.nama}</option>`;
      });
    }
    function fillCards(containerId, jenis) {
      const container = document.getElementById(containerId);
      if (!container) return;
      container.innerHTML = "";
      (grouped[jenis] || []).forEach(p => {
        const label = document.createElement("label");
        label.className = "card-checkbox";

        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "petugas_transmisi[]";
        input.value = p.nama;

        const span = document.createElement("span");
        span.textContent = p.nama;

        label.appendChild(input);
        label.appendChild(span);
        container.appendChild(label);
      });
    }

    fillSelect("petugas_td", "TD");
    fillSelect("petugas_pdu", "PDU");
    fillCards("transmisiCards", "Transmisi");
  } catch (err) {
    console.error("❌ Gagal ambil data petugas:", err);
  }
}

function addTransmisi() {
  const container = document.getElementById("transmisiContainer");
  const select = document.createElement("select");
  select.name = "petugas_transmisi[]";
  select.className = "petugas_transmisi";
  select.setAttribute("data-req", "true");

  if (window.petugasTransmisiOptions) {
    select.innerHTML = window.petugasTransmisiOptions;
  }

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.textContent = "❌ Hapus";
  removeBtn.className = "remove-btn";
  const wrapper = document.createElement("div");
  wrapper.style.marginBottom = "8px";
  removeBtn.onclick = () => container.removeChild(wrapper);

  wrapper.appendChild(select);
  wrapper.appendChild(removeBtn);
  container.appendChild(wrapper);
}

// 🔹 Tambah baris kendala
function addKendala() {
  const container = document.getElementById("kendalaContainer");
  const row = document.createElement("div");
  row.className = "kendala-row";
  row.style.marginBottom = "10px";

  const ket = document.createElement("input");
  ket.type = "text";
  ket.name = "kendala_keterangan[]";
  ket.placeholder = "Keterangan Kendala";

  const waktu = document.createElement("input");
  waktu.type = "time";
  waktu.name = "kendala_waktu[]";

  const foto = document.createElement("input");
  foto.type = "file";
  foto.name = "kendala_foto[]";
  foto.accept = "image/*";

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.textContent = "❌ Hapus";
  removeBtn.className = "remove-btn";
  removeBtn.onclick = () => container.removeChild(row);

  row.append(ket, waktu, foto, removeBtn);
  container.appendChild(row);
}

// 🔹 Progress bar
function updateProgress(step) {
  const steps = document.querySelectorAll(".progress-step");
  steps.forEach((circle, index) => circle.classList.toggle("active", index < step));
  const totalSteps = steps.length;
  const progress = ((step - 1) / (totalSteps - 1)) * 100;
  document.querySelector(".progressbar").style.setProperty("--progress-width", progress + "%");
}

/* ======================
   STEP 3: ACARA DINAMIS
   ====================== */

// Label jam per waktu (display only). Backend tetap pakai acara_15..18.
const SLOT_LABELS = {
  sore: { "15": "15.00 - 15.59", "16": "16.00 - 16.59", "17": "17.00 - 17.59", "18": "18.00 - 18.59" },
  pagi: { "15": "08.00 - 08.59", "16": "09.00 - 09.59", "17": "10.00 - 10.59", "18": "13.00 - 14.59" },
};

function updateSlotHeaders(waktu) {
  const labels = SLOT_LABELS[waktu] || SLOT_LABELS.sore;
  ["15","16","17","18"].forEach(slot => {
    const el = document.getElementById(`slot-title-${slot}`);
    if (el) el.textContent = labels[slot] || el.textContent;
  });
}

let ACARA_LIST = []; // cache hasil API

async function fetchAcara(waktu = "sore") {
  try {
    const res = await fetch(`/api/acara?waktu=${encodeURIComponent(waktu)}`, { cache: "no-store" });
    if (!res.ok) throw new Error("Gagal mengambil data acara");
    ACARA_LIST = await res.json(); // [{id, nama, jenis, waktu}, ...]
  } catch (e) {
    console.error(e);
    ACARA_LIST = [];
  }
}

// value checkbox: "{Nama(Jenis),pagi|sore}"
function makeAcaraCardHTML(item, slot, waktu) {
  const value = `{${item.nama}(${item.jenis}),${waktu}}`;
  const id = `acara_${slot}_${item.id}`;
  return `
    <label class="card-item" title="${item.nama} • ${item.jenis}">
      <input type="checkbox" name="acara_${slot}[]" value="${value}" id="${id}">
      <div class="card">
        <div class="card-title">${item.nama}</div>
        <div class="card-subtitle">${item.jenis}</div>
      </div>
    </label>
  `;
}

function renderAcaraCardsForSlot(slot, waktu) {
  const container = document.getElementById(`acaraCards-${slot}`);
  if (!container) return;

  // Simpan pilihan lama untuk slot yg sama (jika tetap sama waktunya)
  const prevSelected = new Set(
    Array.from(document.querySelectorAll(`input[name="acara_${slot}[]"]:checked`)).map(i => i.value)
  );

  container.innerHTML = "";
  if (!Array.isArray(ACARA_LIST) || ACARA_LIST.length === 0) {
    container.innerHTML = `<div class="muted">Tidak ada data acara untuk ${waktu}.</div>`;
    return;
  }

  container.innerHTML = ACARA_LIST.map(item => makeAcaraCardHTML(item, slot, waktu)).join("");

  // Pulihkan centang bila value yang sama masih ada
  container.querySelectorAll(`input[name="acara_${slot}[]"]`).forEach(inp => {
    if (prevSelected.has(inp.value)) inp.checked = true;
  });
}

async function initAcaraCards() {
  // radio default
  let waktu = "sore";
  const radios = document.querySelectorAll('input[name="waktu_siaran"]');
  radios.forEach(r => { if (r.checked) waktu = r.value; });

  // set header + load awal
  updateSlotHeaders(waktu);
  await fetchAcara(waktu);
  ["15","16","17","18"].forEach(slot => renderAcaraCardsForSlot(slot, waktu));

  // on-change: update header + reload list
  radios.forEach(r => {
    r.addEventListener("change", async (e) => {
      const w = e.target.value;
      updateSlotHeaders(w);
      await fetchAcara(w);
      ["15","16","17","18"].forEach(slot => renderAcaraCardsForSlot(slot, w));
    });
  });
}

// 🔹 Submit via AJAX
document.getElementById("reportForm").addEventListener("submit", async function (e) {
  e.preventDefault();

  const formData = new FormData(this);
  const submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner"></span> Mengirim...`;

  try {
    const res = await fetch("/submit", { method: "POST", body: formData });
    const result = await res.json();

    const statusBox = document.getElementById("statusMessage");
    statusBox.style.color = result.status === "success" ? "green" : "red";

    if (result.status === "success") {
      statusBox.innerHTML = `
        ✅ ${result.message} <br>
        <a href="${result.pdf_url}" target="_blank" class="download-btn">📄 Download PDF</a>
      `;
      this.reset();
      currentStep = 1;
      showStep(currentStep);
      // setelah reset, muat ulang kartu sesuai default (sore)
      initAcaraCards();
    } else {
      statusBox.innerText = result.message;
    }
  } catch (err) {
    document.getElementById("statusMessage").innerText = "Terjadi kesalahan: " + err.message;
  }

  submitBtn.disabled = false;
  submitBtn.innerText = "Submit";
});

// 🔹 Inisialisasi
window.addEventListener("DOMContentLoaded", () => {
  showStep(currentStep);
  loadPetugas();
  initAcaraCards(); // penting: panggil sekali saja
});
