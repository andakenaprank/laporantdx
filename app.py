from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, make_response
import os, io, json, base64, pickle
import gspread
from datetime import datetime, date, timezone, timedelta
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from dotenv import load_dotenv
from PIL import Image
from google.oauth2.service_account import Credentials
from oauth2client.service_account import ServiceAccountCredentials
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy.pool import NullPool
import pathlib
# --- Cloudinary ---
import cloudinary
import cloudinary.uploader as cldu
from cloudinary.utils import cloudinary_url

# -------------------------------------------------------
# Init
# -------------------------------------------------------
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "rahasia-super")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # limit upload 10MB

PDF_DIR = os.path.join(app.root_path, "generated_pdfs")
os.makedirs(PDF_DIR, exist_ok=True)
# ----------------- Database via SQLAlchemy -----------------
def _ensure_sqlalchemy_url_with_ssl(url: str) -> str:
    if not url:
        return url
    p = urlparse(url)
    scheme = p.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+psycopg2"
    qs = {k: v[0] for k, v in parse_qs(p.query).items()}
    if qs.get("sslmode") not in ("require", "verify-ca", "verify-full"):
        qs["sslmode"] = "require"
    return urlunparse(p._replace(scheme=scheme, query=urlencode(qs)))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL tidak ditemukan di environment variables!")
DATABASE_URL = _ensure_sqlalchemy_url_with_ssl(DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    poolclass=NullPool,
    connect_args={"sslmode": "require"},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE laporanx ADD COLUMN IF NOT EXISTS timestamp_wib TIMESTAMP"))

# ----------------- Google Sheets -----------------
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
if os.getenv("GOOGLE_CREDS"):
    creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
    sa_creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
else:
    sa_creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)

client = gspread.authorize(sa_creds)
sheet = client.open_by_key("10u7E3c_IA5irWT0XaKb4eb10taOocH1Q9BK7UrlccDU").sheet1

# ----------------- Cloudinary config -----------------
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)
BASE_FOLDER = os.getenv("CLOUDINARY_BASE_FOLDER", "td")
FOLDER_STUDIO = os.getenv("CLOUDINARY_FOLDER_STUDIO", f"{BASE_FOLDER}/studio")
FOLDER_STREAMING = os.getenv("CLOUDINARY_FOLDER_STREAMING", f"{BASE_FOLDER}/streaming")
FOLDER_SUBCONTROL = os.getenv("CLOUDINARY_FOLDER_SUBCONTROL", f"{BASE_FOLDER}/subcontrol")
FOLDER_KENDALA = os.getenv("CLOUDINARY_FOLDER_KENDALA", f"{BASE_FOLDER}/kendala")
FOLDER_PDF = os.getenv("CLOUDINARY_FOLDER_PDF", f"{BASE_FOLDER}/pdf")

# ----------------- Util Waktu (WIB) -----------------
# Fallback tanpa paket tambahan (UTC+7) jika zoneinfo tak tersedia
from datetime import datetime, date, timezone, timedelta

try:
    # Python 3.9+ (preferred)
    from zoneinfo import ZoneInfo
    TZ_WIB = ZoneInfo("Asia/Jakarta")
except Exception:
    # Fallback tanpa paket eksternal: offset tetap UTC+7
    TZ_WIB = timezone(timedelta(hours=7))

def now_wib_minute_aw() -> datetime:
    return datetime.now(timezone.utc).astimezone(TZ_WIB).replace(second=0, microsecond=0)

def to_naive_wib(dt_aw: datetime) -> datetime:
    if dt_aw is None:
        return None
    if dt_aw.tzinfo is None:
        return dt_aw.replace(second=0, microsecond=0)
    return dt_aw.astimezone(TZ_WIB).replace(tzinfo=None, second=0, microsecond=0)

def fmt_wib(x) -> str:
    if x is None:
        return ""
    if isinstance(x, datetime):
        if x.tzinfo is None:
            return x.strftime("%Y-%m-%d %H:%M")
        return x.astimezone(TZ_WIB).strftime("%Y-%m-%d %H:%M")
    if isinstance(x, date):
        return x.strftime("%Y-%m-%d")
    return str(x)


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
    session["user_id"] = "petugas"
    session["username"] = "petugas"
    session["full_name"] = "Petugas Lapangan"
    session["role"] = "petugas"
    return redirect(url_for("form_laporan"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.before_request
def require_login():
    p = (request.path or "").rstrip("/")  # normalisasi ringan
    ep = request.endpoint  # bisa None jika routing gagal resolve
    # --- DEBUG: logkan rute yang lewat gate ---
    try:
        # Komentar baris ini setelah beres debug
        app.logger.debug(f"[AUTH] path={p} endpoint={ep} logged_in={'user_id' in session}")
    except Exception:
        pass

    # 1) Selalu lolos untuk static & DOWNLOAD PDF (tanpa syarat login)
    if p.startswith("/static") or p.startswith("/download_pdf") or p.startswith("/files/pdf/"):
        return

    # 2) Endpoint publik yang boleh diakses tanpa login
    open_endpoints = {
        "index",
        "form_laporan",
        "submit",
        "download_pdf",
        "api_petugas",
        "login",
        "login_petugas",
    }
    if ep in open_endpoints:
        return

    # 3) Whitelist by PATH (cadangan kalau endpoint == None, atau di balik proxy/subpath)
    public_paths = ("/", "/form", "/submit", "/api/petugas")
    if p in public_paths or any(p.startswith(s) for s in ("/api/petugas",)):
        return

    # 4) API privat → 401 JSON jika belum login
    if p.startswith("/api/") and "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    # 5) Halaman lain → redirect ke login bila belum login
    if "user_id" not in session:
        return redirect(url_for("login", next=request.path))


# ----------------- ADMIN -----------------
@app.route("/admin")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect(url_for("login", next=request.path))
    return render_template("admin.html")

# ----------------- API PETUGAS (Publik) -----------------
@app.route("/api/petugas")
def api_petugas():
    jenis = request.args.get("jenis")
    with engine.connect() as conn:
        if jenis:
            rows = conn.execute(
                text("""
                    SELECT id, nama, jenis
                    FROM petugas2
                    WHERE upper(trim(jenis)) = upper(:j)
                    ORDER BY nama ASC
                """),
                {"j": jenis}
            )
        else:
            rows = conn.execute(text("""
                SELECT id, nama, jenis
                FROM petugas2
                ORDER BY upper(trim(jenis)), nama ASC
            """))
        data = [dict(row._mapping) for row in rows]

    app.logger.info("API /api/petugas -> %d rows; sample=%s", len(data), data[:3] if data else [])
    resp = jsonify(data)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

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
        d["tanggal"] = fmt_wib(d.get("tanggal"))
        d["timestamp_wib"] = fmt_wib(d.get("timestamp_wib"))
        data.append(d)
    return jsonify(data)

# ----------------- Cloudinary Upload Helpers -----------------
def _upload_image_to_cloudinary(file, folder: str, public_id_base: str) -> str:
    """Kompres ke JPEG dan upload ke Cloudinary. Return secure_url atau ''."""
    if not file or not getattr(file, "filename", ""):
        return ""
    try:
        # kompres -> JPEG
        img = Image.open(file.stream).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", optimize=True, quality=70)
        buf.seek(0)

        safe_base = (public_id_base or "bukti").strip().replace("/", "-").replace(" ", "_")
        res = cldu.upload(
            buf,
            folder=folder,
            public_id=safe_base,
            type="upload", 
            access_mode="public",         # Cloudinary akan menambah suffix unik bila overwrite=False
            resource_type="image",
            overwrite=False,
            format="jpg",
        )
        return res.get("secure_url", "") or res.get("url", "")
    except Exception:
        app.logger.exception("Cloudinary image upload failed")
        return ""


def _build_signed_raw_url(public_id_path: str, version: int | None = None) -> str:
    """
    Buat URL bertanda tangan untuk RAW (PDF) di Cloudinary.
    Arg public_id_path adalah path penuh TANPA ekstensi, mis: 'td/pdf/laporan_65'
    Version gunakan nilai 'version' dari hasil upload agar URL tidak 404.
    """
    # Pastikan tanpa ekstensi
    pid = public_id_path
    if pid.lower().endswith(".pdf"):
        pid = pid[:-4]

    url, _ = cloudinary_url(
        pid,
        resource_type="raw",
        type="authenticated",   # delivery authenticated
        sign_url=True,          # tambahkan signature
        secure=True,
        format="pdf",           # ekstensi ditangani oleh 'format', jadi tidak ganda
        version=version,        # gunakan versi yang benar (v1760…)
    )
    return url

def _upload_pdf_to_cloudinary(pdf_bytes: bytes, folder: str, public_id_base: str) -> str:
    if not pdf_bytes:
        return ""
    try:
        buf = io.BytesIO(pdf_bytes); buf.seek(0)
        safe_base = (public_id_base or "laporan").strip().replace("/", "-").replace(" ", "_")

        # Upload sebagai RAW + AUTHENTICATED (sesuai kebijakan akun kamu yang memaksa auth)
        res = cldu.upload(
            buf,
            folder=folder,
            public_id=safe_base,     # tanpa .pdf
            resource_type="raw",
            type="authenticated",    # penting!
            overwrite=True,
            format="pdf",            # simpan sebagai pdf
        )

        public_id = res.get("public_id", "")     # contoh: 'td/pdf/laporan_65'
        version   = res.get("version", None)     # contoh: 1760329270 (int)
        dtype     = res.get("type")
        rtype     = res.get("resource_type")
        app.logger.info("Cloudinary PDF uploaded: public_id=%s version=%s type=%s rtype=%s url=%s",
                        public_id, version, dtype, rtype, res.get("secure_url"))

        # Bangun signed authenticated URL dengan versi yang benar
        return _build_signed_raw_url(public_id, version=version)
    except Exception:
        app.logger.exception("Cloudinary PDF upload failed")
        return ""



# ----------------- PDF Builder (return bytes) -----------------
def build_pdf_bytes(row_dict: dict) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    def safe(s):
        return "" if s is None else str(s)

    base_style = styles["Normal"]
    link_style = ParagraphStyle("link", parent=base_style, fontSize=9, leading=12)

    def esc_html(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def linkify(url: str):
        if not url:
            return Paragraph("-", link_style)
        u = url.strip()
        display = u if len(u) <= 60 else (u[:57] + "...")
        return Paragraph(f'<a href="{esc_html(u)}">{esc_html(display)}</a>', link_style)

    # Header
    elements.append(Paragraph("LAPORAN TEKNIS HARIAN", styles["Heading1"]))
    elements.append(Spacer(1, 12))

    # Identitas
    identitas = [
        ["ID", safe(row_dict.get("id"))],
        ["Timestamp (WIB)", fmt_wib(row_dict.get("timestamp_wib"))],
        ["Tanggal", fmt_wib(row_dict.get("tanggal"))],
        ["Petugas TD", safe(row_dict.get("nama_td"))],
        ["Petugas PDU", safe(row_dict.get("nama_pdu"))],
        ["Petugas Transmisi", safe(row_dict.get("nama_tx"))],
    ]
    t1 = Table(identitas, colWidths=[150, 300])
    t1.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(Paragraph("Step 1: Identitas Petugas", styles["Heading3"]))
    elements.append(t1)
    elements.append(Spacer(1, 12))

    # Bukti
    bukti = [
        ["Studio",     linkify(safe(row_dict.get("studio_link")))],
        ["Streaming",  linkify(safe(row_dict.get("streaming_link")))],
        ["Subcontrol", linkify(safe(row_dict.get("subcontrol_link")))],
    ]
    t2 = Table(bukti, colWidths=[150, 300])
    t2.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)
    ]))
    elements.append(Paragraph("Step 2: Bukti (tautan)", styles["Heading3"]))
    elements.append(t2)
    elements.append(Spacer(1, 12))

    # Acara
    acara = [
        ["15.00-15.59", safe(row_dict.get("acara_15")), safe(row_dict.get("format_15"))],
        ["16.00-16.59", safe(row_dict.get("acara_16")), safe(row_dict.get("format_16"))],
        ["17.00-17.59", safe(row_dict.get("acara_17")), safe(row_dict.get("format_17"))],
        ["18.00-18.59", safe(row_dict.get("acara_18")), safe(row_dict.get("format_18"))],
    ]
    t3 = Table([["Jam", "Acara", "Format"]] + acara, colWidths=[100, 200, 150])
    t3.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOX", (0,0), (-1,-1), 1, colors.black),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
    ]))
    elements.append(Paragraph("Step 3: Acara - Acara", styles["Heading3"]))
    elements.append(t3)
    elements.append(Spacer(1, 12))

    # Kendala
    kendalas = []
    def _split_or_empty(v):
        if not v:
            return []
        return [s.strip() for s in str(v).split(",") if s is not None]

    kets = _split_or_empty(row_dict.get("kendala"))
    wkt  = _split_or_empty(row_dict.get("waktu_kendala"))
    lks  = _split_or_empty(row_dict.get("link_kendala"))

    n = max(len(kets), len(wkt), len(lks))
    for i in range(n):
        ket = kets[i] if i < len(kets) and kets[i] else "-"
        wk  = wkt[i]  if i < len(wkt)  and wkt[i]  else "-"
        lk  = lks[i]  if i < len(lks)  and lks[i]  else ""
        kendalas.append([ket, wk, linkify(lk) if lk else Paragraph("-", link_style)])

    if kendalas:
        t4 = Table([["Keterangan", "Waktu", "Link"]] + kendalas, colWidths=[200, 100, 200])
        t4.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("BOX", (0,0), (-1,-1), 1, colors.black),
            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)
        ]))
        elements.append(Paragraph("Step 4: Kendala - Kendala", styles["Heading3"]))
        elements.append(t4)

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Kesimpulan: <b>{safe(row_dict.get('kesimpulan'))}</b>", styles["Heading2"]))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()

# ----------------- ROUTES HALAMAN -----------------
@app.route("/")
def index():
    return redirect(url_for("form_laporan"))

@app.route("/form")
def form_laporan():
    return render_template("index.html")

# ----------------- SUBMIT FORM (Sore / laporanx) -----------------
@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.form.to_dict(flat=False)

        # Timestamp WIB
        ts_wib_aw = now_wib_minute_aw()
        ts_wib_naive = to_naive_wib(ts_wib_aw)
        ts_str_for_name = ts_wib_aw.strftime("%Y-%m-%d_%H-%M")
        ts_str_for_sheet = ts_wib_aw.strftime("%Y-%m-%d %H:%M")

        # tanggal_manual → DATE
        tgl_str = (data.get("tanggal_manual", [""])[0] or "").strip()
        if tgl_str:
            try:
                tanggal_date = date.fromisoformat(tgl_str)
            except ValueError:
                tanggal_date = ts_wib_aw.date()
        else:
            tanggal_date = ts_wib_aw.date()

        # petugas transmisi multi
        petugas_transmisi_list = data.get("petugas_transmisi[]", [])
        petugas_transmisi = ", ".join(petugas_transmisi_list)

        # Upload bukti (ke Cloudinary)
        studio_file = request.files.get("bukti_studio")
        streaming_file = request.files.get("bukti_streaming")
        subcontrol_file = request.files.get("bukti_subcontrol")

        studio_link = _upload_image_to_cloudinary(studio_file, FOLDER_STUDIO, f"studio_{ts_str_for_name}") if studio_file else ""
        streaming_link = _upload_image_to_cloudinary(streaming_file, FOLDER_STREAMING, f"streaming_{ts_str_for_name}") if streaming_file else ""
        subcontrol_link = _upload_image_to_cloudinary(subcontrol_file, FOLDER_SUBCONTROL, f"subcontrol_{ts_str_for_name}") if subcontrol_file else ""

        # Kendala (opsional) → daftar link Cloudinary
        fotos = request.files.getlist("kendala_foto[]")
        folder_links = []
        for i, foto in enumerate(fotos):
            if foto and getattr(foto, "filename", ""):
                keterangan_list = data.get("kendala_keterangan[]", [])
                waktu_list = data.get("kendala_waktu[]", [])
                keterangan = (keterangan_list[i] if i < len(keterangan_list) else "") or "kendala"
                waktu_input = waktu_list[i] if i < len(waktu_list) else ""
                waktu_for_name = waktu_input.replace(":", "-") if waktu_input else ts_str_for_name
                public_id_base = f"{keterangan}_{waktu_for_name}".replace(" ", "_")
                link = _upload_image_to_cloudinary(foto, FOLDER_KENDALA, public_id_base)
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

        # Simpan DB
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
            "tanggal": tanggal_date,
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
            "timestamp_wib": ts_wib_naive,
        }

        with engine.begin() as conn:
            result = conn.execute(sql, values)
            last_id = result.fetchone()[0]

        # Simpan ke Sheets
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
            ts_str_for_sheet,
        ]
        sheet.append_row(sheet_row)

        # Bangun PDF (bytes) lalu upload ke Cloudinary → dapatkan URL
        # Ambil ulang row untuk isi PDF (agar id dan timestamp dari DB konsisten)
                # Bangun PDF (bytes) lalu SIMPAN LOKAL
        with engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM laporanx WHERE id=:id"), {"id": last_id}).fetchone()

        pdf_bytes = build_pdf_bytes(dict(row._mapping))
        filename = f"laporan_{last_id}.pdf"
        save_path = os.path.join(PDF_DIR, filename)
        with open(save_path, "wb") as f:
            f.write(pdf_bytes)

        # URL publik (lokal) untuk membuka PDF
        pdf_url = url_for("serve_local_pdf", filename=filename, _external=True)

        return jsonify({
            "status": "success",
            "message": "Laporan berhasil disimpan!",
            "pdf_url": pdf_url  # ← sekarang URL lokal, bukan Cloudinary
        })

    except Exception as e:
        app.logger.exception("Submit gagal")
        return jsonify({"status": "error", "message": str(e)})

@app.route("/files/pdf/<path:filename>")
def serve_local_pdf(filename):
    # keamanan sederhana: hanya izinkan pola nama file yang kita buat
    if not filename.startswith("laporan_") or not filename.endswith(".pdf"):
        return make_response(("Not found", 404))
    full_path = pathlib.Path(PDF_DIR) / filename
    try:
        full_path = full_path.resolve()
        if not str(full_path).startswith(str(pathlib.Path(PDF_DIR).resolve())):
            return make_response(("Not found", 404))
        if not full_path.exists():
            return make_response(("Not found", 404))

        with open(full_path, "rb") as f:
            data = f.read()
        resp = make_response(data)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = f'inline; filename="{filename}"'
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception:
        app.logger.exception("Gagal menyajikan PDF lokal")
        return make_response(("Gagal memuat PDF", 500))
# ----------------- DOWNLOAD PDF (opsional, legacy) -----------------
# Masih tersedia kalau kamu butuh download langsung dari server.
@app.route("/download_pdf/<int:laporan_id>")
def download_pdf(laporan_id):
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM laporanx WHERE id=:id"),
                {"id": laporan_id}
            ).fetchone()
    except Exception as e:
        app.logger.exception("DB error saat ambil laporan")
        return make_response(("Database error: " + str(e), 500))

    if not row:
        return make_response(("Laporan tidak ditemukan", 404))

    try:
        pdf_bytes = build_pdf_bytes(dict(row._mapping))
        if not pdf_bytes:
            return make_response(("PDF kosong/invalid", 500))

        # Sajikan INLINE agar browser bisa render langsung (bukan download paksa)
        resp = make_response(pdf_bytes)
        resp.headers["Content-Type"] = "application/pdf"
        resp.headers["Content-Disposition"] = f'inline; filename="laporan_{laporan_id}.pdf"'
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as e:
        app.logger.exception("PDF build error")
        return make_response(("PDF build error: " + str(e), 500))


# ----------------- RUN APP -----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
