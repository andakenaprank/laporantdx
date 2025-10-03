from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
import os, io, json
import gspread
from datetime import datetime, timezone, timedelta
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image
from google.oauth2.service_account import Credentials
from oauth2client.service_account import ServiceAccountCredentials
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "rahasia-super")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # limit upload 10MB

# ----------------- Database via SQLAlchemy -----------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL tidak ditemukan di environment variables!")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Pastikan kolom timestamp ada (nama lama 'timestamp_wib' untuk kompatibilitas; isinya WITA)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE laporanx ADD COLUMN IF NOT EXISTS timestamp_wib TIMESTAMP"))

# ----------------- Google Sheets + Drive (Service Account) -----------------
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
if os.getenv("GOOGLE_CREDS"):
    creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
    sa_creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
else:
    # fallback file lokal (jika dipakai)
    sa_creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)

# Sheets client
client = gspread.authorize(sa_creds)
# Ganti key sesuai sheet kamu
sheet = client.open_by_key("10u7E3c_IA5irWT0XaKb4eb10taOocH1Q9BK7UrlccDU").sheet1

# Drive service via Service Account (stabil, tidak perlu GOOGLE_TOKEN)
# === Drive pakai OAuth User (punya kuota) ===
import base64, pickle

token_b64 = os.getenv("GOOGLE_TOKEN")
if not token_b64:
    raise RuntimeError("❌ GOOGLE_TOKEN tidak ditemukan di environment variables! Lihat instruksi pembuatan token OAuth Desktop.")
user_creds = pickle.loads(base64.b64decode(token_b64))
drive_service = build("drive", "v3", credentials=user_creds)


# 🔹 Folder ID Google Drive (PASTIKAN ke-4 folder di-share ke email Service Account ini)
STUDIO_FOLDER = "10qkm0wFbtCeG6qSoHbIEylivSew8gH0u"
STREAMING_FOLDER = "1avnAbIZQ7jjlqsNVNEERPqDR6BruSi8t"
SUBCONTROL_FOLDER = "15Su0y-6gchdmHyijoSwMvgQW8NV9osna"
KENDALA_FOLDER = "101Biqep6gDbxzcFbcel02VWW31masi_T"

# ----------------- Util -----------------
# Definisi WITA manual (UTC+8) supaya bebas dari tzdata server
WITA = timezone(timedelta(hours=8))

def now_wita_minute():
    return datetime.now(WITA).replace(second=0, microsecond=0)

def fmt_wita(dt):
    if not dt:
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)

# ----------------- AUTH -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, username, password_hash, full_name FROM admins WHERE username=:u"),
                {"u": username}
            ).fetchone()

        if result and check_password_hash(result[2], password):
            session["user_id"] = result[0]
            session["username"] = result[1]
            session["full_name"] = result[3]
            session["role"] = "admin"
            return redirect(url_for("admin_dashboard"))
        else:
            return render_template("login.html", error="Username atau password salah")

    return render_template("login.html")

@app.route("/login_petugas")
def login_petugas():
    # tetap ada jika tombol lama masih memakai ini
    session["user_id"] = "petugas"
    session["username"] = "petugas"
    session["full_name"] = "Petugas Lapangan"
    session["role"] = "petugas"
    return redirect(url_for("form_laporan"))  # ke form (publik)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.before_request
def require_login():
    # izinkan static files
    if request.path.startswith("/static/"):
        return

    # endpoint publik
    open_endpoints = {
        "login",
        "login_petugas",
        "index",            # redirect ke login
        "form_laporan",     # form laporan petugas (publik)
        "submit",           # submit form (publik)
        "download_pdf",     # unduh PDF (publik)
        "api_petugas",      # daftar petugas (publik)
    }

    if request.endpoint in open_endpoints:
        return

    if "user_id" not in session:
        if request.path.startswith("/api/"):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for("login"))

# ----------------- ADMIN -----------------
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect(url_for("login"))
    return render_template("admin.html")

# ----------------- API PETUGAS (Publik) -----------------
@app.route("/api/petugas")
def api_petugas():
    jenis = request.args.get("jenis")
    with engine.connect() as conn:
        if jenis:
            rows = conn.execute(
                text("SELECT id, nama, jenis FROM petugas2 WHERE jenis=:j ORDER BY nama ASC"),
                {"j": jenis}
            )
        else:
            rows = conn.execute(text("SELECT id, nama, jenis FROM petugas2 ORDER BY jenis, nama ASC"))
        data = [dict(row._mapping) for row in rows]
    return jsonify(data)

# ----------------- API LAPORAN (Admin only) -----------------
@app.route("/api/laporan")
def api_laporan():
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM laporanx ORDER BY id DESC")).fetchall()

    data = []
    for r in rows:
        d = dict(r._mapping)
        d["tanggal"] = fmt_wita(d.get("tanggal"))
        d["timestamp_wib"] = fmt_wita(d.get("timestamp_wib"))  # berisi waktu WITA
        data.append(d)
    return jsonify(data)

# ----------------- UPLOAD DRIVE (Service Account) -----------------
def upload_to_drive(file, keterangan, waktu_str, folder_id):
    if not file or not getattr(file, "filename", ""):
        app.logger.warning("No file received for upload_to_drive")
        return ""

    try:
        # Amankan nama dasar (fallback)
        orig_name = secure_filename(file.filename) or "bukti.jpg"

        # Baca & kompres ke JPEG
        img = Image.open(file.stream)
        img = img.convert("RGB")
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=70)
        buffer.seek(0)

        # Nama file di Drive
        safe_ket = (keterangan or "bukti").strip().replace("/", "-").replace(" ", "_")
        safe_waktu = (waktu_str or "").strip().replace(":", "-").replace(" ", "_")
        base = safe_ket or os.path.splitext(orig_name)[0] or "bukti"
        filename = f"{base}_{safe_waktu}.jpg" if safe_waktu else f"{base}.jpg"

        file_metadata = {"name": filename, "parents": [folder_id]}
        media = MediaIoBaseUpload(buffer, mimetype="image/jpeg", resumable=False)
        uploaded = drive_service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()

        fid = uploaded.get("id")
        if not fid:
            app.logger.error("Drive upload returned no file id")
            return ""
        link = f"https://drive.google.com/file/d/{fid}/view?usp=sharing"
        app.logger.info(f"Drive uploaded: {filename} -> {link}")
        return link

    except Exception:
        app.logger.exception("Drive upload failed")
        return ""

# ----------------- ROUTES HALAMAN -----------------
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/form")
def form_laporan():
    return render_template("index.html")  # form laporan petugas (publik)

# ----------------- SUBMIT FORM -----------------
@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.form.to_dict(flat=False)

        # 🔹 Timestamp WITA (akurasi menit)
        ts_wita = now_wita_minute()
        ts_str_for_name = ts_wita.strftime("%Y-%m-%d_%H-%M")
        ts_str_for_sheet = ts_wita.strftime("%Y-%m-%d %H:%M")

        # tanggal_manual → jika kosong pakai ts_wita
        tanggal_manual = (data.get("tanggal_manual", [""])[0] or "").strip()
        if tanggal_manual:
            try:
                tanggal = datetime.strptime(tanggal_manual, "%Y-%m-%d")
            except ValueError:
                tanggal = ts_wita
        else:
            tanggal = ts_wita

        # petugas transmisi multi
        petugas_transmisi_list = data.get("petugas_transmisi[]", [])
        petugas_transmisi = ", ".join(petugas_transmisi_list)

        # Upload bukti
        studio_file = request.files.get("bukti_studio")
        streaming_file = request.files.get("bukti_streaming")
        subcontrol_file = request.files.get("bukti_subcontrol")

        studio_link = upload_to_drive(studio_file, "studio", ts_str_for_name, STUDIO_FOLDER) if studio_file else ""
        streaming_link = upload_to_drive(streaming_file, "streaming", ts_str_for_name, STREAMING_FOLDER) if streaming_file else ""
        subcontrol_link = upload_to_drive(subcontrol_file, "subcontrol", ts_str_for_name, SUBCONTROL_FOLDER) if subcontrol_file else ""

        # Kendala (opsional)
        fotos = request.files.getlist("kendala_foto[]")
        folder_links = []
        for i, foto in enumerate(fotos):
            if foto and getattr(foto, "filename", ""):
                keterangan = data.get("kendala_keterangan[]", [""])[i] if i < len(data.get("kendala_keterangan[]", [])) else ""
                waktu_input = data.get("kendala_waktu[]", [""])[i] if i < len(data.get("kendala_waktu[]", [])) else ""
                waktu_for_name = waktu_input.replace(":", "-") if waktu_input else ts_str_for_name
                link = upload_to_drive(foto, keterangan or "kendala", waktu_for_name, KENDALA_FOLDER)
                if link:
                    folder_links.append(link)
        folder_link_str = ", ".join(folder_links)

        # Kesimpulan sederhana
        kesimpulan = "lancar"
        waktu_kendala_list = data.get("kendala_waktu[]", [])
        ada_sebelum, ada_sesudah = False, False
        for w in waktu_kendala_list:
            if not w:
                continue
            try:
                jam, _ = map(int, w.split(":"))
                if jam < 15:
                    ada_sebelum = True
                else:
                    ada_sesudah = True
            except Exception:
                pass
        if ada_sebelum and ada_sesudah:
            kesimpulan = "kurang lancar"
        elif ada_sebelum:
            kesimpulan = "ada kendala sebelum siaran"
        elif ada_sesudah:
            kesimpulan = "ada kendala saat siaran"

        # Simpan DB (kolom timestamp_wib berisi WITA)
        sql = text("""
        INSERT INTO laporanx (
            tanggal, nama_td, nama_pdu, nama_tx,
            studio_link, streaming_link, subcontrol_link,
            acara_15, format_15, acara_16, format_16,
            acara_17, format_17, acara_18, format_18,
            kendala, waktu_kendala, link_kendala, kesimpulan,
            timestamp_wib
        ) VALUES (
            :tanggal, :nama_td, :nama_pdu, :nama_tx,
            :studio_link, :streaming_link, :subcontrol_link,
            :acara_15, :format_15, :acara_16, :format_16,
            :acara_17, :format_17, :acara_18, :format_18,
            :kendala, :waktu_kendala, :link_kendala, :kesimpulan,
            :timestamp_wib
        ) RETURNING id
        """)

        values = {
            "tanggal": tanggal,
            "nama_td": data.get("petugas_td", [""])[0],
            "nama_pdu": data.get("petugas_pdu", [""])[0],
            "nama_tx": petugas_transmisi,
            "studio_link": studio_link,
            "streaming_link": streaming_link,
            "subcontrol_link": subcontrol_link,
            "acara_15": data.get("acara_15", [""])[0],
            "format_15": data.get("format_15", [""])[0],
            "acara_16": data.get("acara_16", [""])[0],
            "format_16": data.get("format_16", [""])[0],
            "acara_17": data.get("acara_17", [""])[0],
            "format_17": data.get("format_17", [""])[0],
            "acara_18": data.get("acara_18", [""])[0],
            "format_18": data.get("format_18", [""])[0],
            "kendala": ", ".join(data.get("kendala_keterangan[]", [])),
            "waktu_kendala": ", ".join(waktu_kendala_list),
            "link_kendala": folder_link_str,
            "kesimpulan": kesimpulan,
            "timestamp_wib": ts_wita  # nilai WITA
        }

        with engine.begin() as conn:
            result = conn.execute(sql, values)
            last_id = result.fetchone()[0]

        # Simpan ke Sheets (timestamp ditaruh kolom paling kanan)
        sheet_row = [
            str(values["tanggal"]),
            values["nama_td"],
            values["nama_pdu"],
            values["nama_tx"],
            values["studio_link"],
            values["streaming_link"],
            values["subcontrol_link"],
            values["acara_15"], values["format_15"],
            values["acara_16"], values["format_16"],
            values["acara_17"], values["format_17"],
            values["acara_18"], values["format_18"],
            values["kendala"],
            values["waktu_kendala"],
            values["link_kendala"],
            values["kesimpulan"],
        ]
        sheet_row.append(ts_str_for_sheet)  # Timestamp (WITA) di paling kanan
        sheet.append_row(sheet_row)

        # Log supaya mudah cek di server
        app.logger.info(f"Studio link: {studio_link}")
        app.logger.info(f"Streaming link: {streaming_link}")
        app.logger.info(f"Subcontrol link: {subcontrol_link}")
        app.logger.info(f"Kendala links: {folder_link_str}")

        return jsonify({
            "status": "success",
            "message": "Laporan berhasil disimpan!",
            "pdf_url": f"/download_pdf/{last_id}"
        })

    except Exception as e:
        app.logger.exception("Submit gagal")
        return jsonify({"status": "error", "message": str(e)})

# ----------------- DOWNLOAD PDF -----------------
@app.route("/download_pdf/<int:laporan_id>")
def download_pdf(laporan_id):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM laporanx WHERE id=:id"), {"id": laporan_id}).fetchone()

    if not row:
        return "Laporan tidak ditemukan", 404

    data = dict(row._mapping)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("LAPORAN TEKNIS HARIAN", styles["Heading1"]))
    elements.append(Spacer(1, 12))

    identitas = [
        ["ID", str(data.get("id"))],
        ["Timestamp (WITA)", fmt_wita(data.get("timestamp_wib"))],  # berisi waktu WITA
        ["Tanggal", fmt_wita(data.get("tanggal"))],
        ["Petugas TD", data.get("nama_td")],
        ["Petugas PDU", data.get("nama_pdu")],
        ["Petugas Transmisi", data.get("nama_tx")],
    ]
    t1 = Table(identitas, colWidths=[150, 300])
    t1.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(Paragraph("Step 1: Identitas Petugas", styles["Heading3"]))
    elements.append(t1)
    elements.append(Spacer(1, 12))

    # Bukti
    bukti = [
        ["Studio", f'<font color="blue"><u>{data.get("studio_link","")}</u></font>'],
        ["Streaming", f'<font color="blue"><u>{data.get("streaming_link","")}</u></font>'],
        ["Subcontrol", f'<font color="blue"><u>{data.get("subcontrol_link","")}</u></font>'],
    ]
    bukti_rows = [[Paragraph(r[0], styles["Normal"]), Paragraph(r[1], styles["Normal"])] for r in bukti]
    t2 = Table(bukti_rows, colWidths=[150, 300])
    t2.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(Paragraph("Step 2: Bukti", styles["Heading3"]))
    elements.append(t2)
    elements.append(Spacer(1, 12))

    # Acara
    acara = [
        ["15.00-15.59", data.get("acara_15"), data.get("format_15")],
        ["16.00-16.59", data.get("acara_16"), data.get("format_16")],
        ["17.00-17.59", data.get("acara_17"), data.get("format_17")],
        ["18.00-18.59", data.get("acara_18"), data.get("format_18")],
    ]
    t3 = Table([["Jam", "Acara", "Format"]] + acara, colWidths=[100, 200, 150])
    t3.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
    ]))
    elements.append(Paragraph("Step 3: Acara - Acara", styles["Heading3"]))
    elements.append(t3)
    elements.append(Spacer(1, 12))

    # Kendala
    kendalas = []
    kets = (data.get("kendala") or "").split(",") if data.get("kendala") else []
    wkt = (data.get("waktu_kendala") or "").split(",") if data.get("waktu_kendala") else []
    lks = (data.get("link_kendala") or "").split(",") if data.get("link_kendala") else []
    for i in range(max(len(kets), len(wkt), len(lks))):
        kendalas.append([
            kets[i] if i < len(kets) else "-",
            wkt[i] if i < len(wkt) else "-",
            f'<font color="blue"><u>{lks[i]}</u></font>' if i < len(lks) and lks[i] else "-"
        ])
    if kendalas:
        kendala_rows = [[Paragraph(c, styles["Normal"]) for c in row] for row in kendalas]
        t4 = Table([["Keterangan", "Waktu", "Link"]] + kendala_rows, colWidths=[200, 100, 200])
        t4.setStyle(TableStyle([
            ("BOX", (0,0), (-1,-1), 1, colors.black),
            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
        ]))
        elements.append(Paragraph("Step 4: Kendala - Kendala", styles["Heading3"]))
        elements.append(t4)

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Kesimpulan: <b>{data.get('kesimpulan','')}</b>", styles["Heading2"]))

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer,
                     as_attachment=True,
                     download_name=f"laporan_{laporan_id}.pdf",
                     mimetype="application/pdf")

if __name__ == "__main__":
    app.run(debug=True)
