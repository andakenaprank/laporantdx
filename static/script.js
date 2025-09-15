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
function nextStep() {
  if (validateStep(currentStep)) {
    currentStep++;
    showStep(currentStep);
  }
}

function prevStep() {
  currentStep--;
  showStep(currentStep);
}

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
    const res = await fetch("/api/petugas");
    const data = await res.json();

    // kelompokkan berdasarkan jenis
    const grouped = {};
    data.forEach(p => {
      if (!grouped[p.jenis]) grouped[p.jenis] = [];
      grouped[p.jenis].push(p);
    });

    function fillSelect(selectId, jenis) {
      const select = document.getElementById(selectId);
      if (!select) return;
      select.innerHTML = "<option value=''>-- Pilih --</option>";
      if (grouped[jenis]) {
        grouped[jenis].forEach(p => {
          select.innerHTML += `<option value="${p.nama}">${p.nama}</option>`;
        });
      }
    }
    function fillCards(containerId, jenis) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (grouped[jenis]) {
    grouped[jenis].forEach(p => {
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

  // isi opsi dari cache petugas Transmisi
  if (window.petugasTransmisiOptions) {
    select.innerHTML = window.petugasTransmisiOptions;
  }

  // tombol hapus
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.textContent = "❌ Hapus";
  removeBtn.className = "remove-btn";
  removeBtn.onclick = () => container.removeChild(wrapper);

  // wrapper untuk 1 baris
  const wrapper = document.createElement("div");
  wrapper.style.marginBottom = "8px";
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
  steps.forEach((circle, index) => {
    circle.classList.toggle("active", index < step);
  });

  const totalSteps = steps.length;
  const progress = ((step - 1) / (totalSteps - 1)) * 100;
  document.querySelector(".progressbar").style.setProperty("--progress-width", progress + "%");
}

// 🔹 Submit via AJAX
document.getElementById("reportForm").addEventListener("submit", async function (e) {
  e.preventDefault();

  const formData = new FormData(this);
  const submitBtn = this.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner"></span> Mengirim...`;

  try {
    const res = await fetch("/submit", {
      method: "POST",
      body: formData
    });
    const result = await res.json();

    const statusBox = document.getElementById("statusMessage");
    statusBox.style.color = result.status === "success" ? "green" : "red";

    if (result.status === "success") {
      statusBox.innerHTML = `
        ✅ ${result.message} <br>
        <a href="${result.pdf_url}" target="_blank" class="download-btn">
          📄 Download PDF
        </a>
      `;

      this.reset();
      currentStep = 1;
      showStep(currentStep);
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
});
