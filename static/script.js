let currentStep = 1;

function showStep(step) {
  const steps = document.querySelectorAll('.form-step');
  steps.forEach((el, index) => {
    if (index === step - 1) {
      el.classList.add('active');
      el.querySelectorAll('[data-req="true"]').forEach(input => input.required = true);
    } else {
      el.classList.remove('active');
      el.querySelectorAll('[data-req="true"]').forEach(input => input.required = false);
    }
  });

  updateProgress(step);
}

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

function validateStep(step) {
  const currentStepDiv = document.querySelector(`#step-${step}`);
  const inputs = currentStepDiv.querySelectorAll('[data-req="true"]');
  for (let input of inputs) {
    if (!input.value.trim()) {
      input.focus();
      alert("Harap isi semua field sebelum lanjut!");
      return false;
    }
  }
  return true;
}

// 🔹 PROGRESS BAR
function updateProgress(step) {
  const steps = document.querySelectorAll(".progress-step");
  steps.forEach((circle, index) => {
    circle.classList.toggle("active", index < step);
  });

  const totalSteps = steps.length;
  const progress = ((step - 1) / (totalSteps - 1)) * 100;
  document.querySelector(".progressbar").style.setProperty("--progress-width", progress + "%");
}

// 🔹 Tambah Kendala
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

  const bukti = document.createElement("input");
  bukti.type = "url";
  bukti.name = "kendala_bukti[]";
  bukti.placeholder = "Link Bukti Kendala";

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.textContent = "❌";
  removeBtn.style.marginLeft = "5px";
  removeBtn.onclick = () => container.removeChild(row);

  row.appendChild(ket);
  row.appendChild(waktu);
  row.appendChild(bukti);
  row.appendChild(removeBtn);
  container.appendChild(row);
}

// 🔹 Submit AJAX
document.getElementById("reportForm").addEventListener("submit", async function (e) {
  e.preventDefault();

  const formData = new FormData(this);

  try {
    const res = await fetch("/submit", {
      method: "POST",
      body: formData
    });
    const result = await res.json();

    const statusBox = document.getElementById("statusMessage");
    statusBox.innerText = result.message;
    statusBox.style.color = result.status === "success" ? "green" : "red";

    if (result.status === "success") {
  const statusBox = document.getElementById("statusMessage");
  statusBox.innerHTML = `
    ✅ ${result.message} <br>
    <a href="${result.pdf_url}" target="_blank" class="download-btn">
      📄 Download PDF
    </a>
  `;

  // Reset form setelah submit
  this.reset();
  currentStep = 1;
  showStep(currentStep);
}
  } catch (err) {
    document.getElementById("statusMessage").innerText = "Terjadi kesalahan: " + err.message;
  }
});

// 🔹 Inisialisasi
showStep(currentStep);
