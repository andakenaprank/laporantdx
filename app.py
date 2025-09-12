from flask import Flask, render_template, request, jsonify, send_file
import os, io, json, pickle
import psycopg2
import gspread
from datetime import datetime
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
import base64, pickle
load_dotenv()
app = Flask(__name__)

# 🔹 Database connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("❌ DATABASE_URL tidak ditemukan di environment variables!")

db = psycopg2.connect(DATABASE_URL, sslmode="require")
cursor = db.cursor()

# 🔹 Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]

if os.getenv("GOOGLE_CREDS"):
    creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
else:
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)

client = gspread.authorize(creds)
sheet = client.open_by_key("10u7E3c_IA5irWT0XaKb4eb10taOocH1Q9BK7UrlccDU").sheet1

# 🔹 Load OAuth Token (user delegated)
token_b64 = os.getenv("GOOGLE_TOKEN")
if not token_b64:
    raise RuntimeError("❌ GOOGLE_TOKEN tidak ditemukan di environment variables!")

token_data = base64.b64decode(token_b64)
creds = pickle.loads(token_data)

# 🔹 Folder ID masing-masing kategori
STUDIO_FOLDER = "10qkm0wFbtCeG6qSoHbIEylivSew8gH0u"
STREAMING_FOLDER = "1avnAbIZQ7jjlqsNVNEERPqDR6BruSi8t"
SUBCONTROL_FOLDER = "15Su0y-6gchdmHyijoSwMvgQW8NV9osna"
KENDALA_FOLDER = "101Biqep6gDbxzcFbcel02VWW31masi_T"

# 🔹 Fungsi upload ke Google Drive
def upload_to_drive(file, keterangan, waktu_str, folder_id):
    img = Image.open(file)
    img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", optimize=True, quality=70)
    buffer.seek(0)

    safe_ket = keterangan.replace(" ", "_").replace("/", "-")
    safe_waktu = waktu_str.replace(":", "-").replace(" ", "_")
    filename = f"{safe_ket}_{safe_waktu}.jpg"

    service = build("drive", "v3", credentials=creds)
    file_metadata = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(buffer, mimetype="image/jpeg")
    uploaded = service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()

    file_id = uploaded.get("id")
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.form.to_dict(flat=False)
        now = datetime.now()                 # untuk database
        now_str = now.strftime("%Y-%m-%d_%H-%M-%S")  # untuk nama file

        # 🔹 Upload bukti ke folder masing-masing
        studio_file = request.files.get("bukti_studio")
        streaming_file = request.files.get("bukti_streaming")
        subcontrol_file = request.files.get("bukti_subcontrol")

        studio_link = upload_to_drive(studio_file, "studio", now_str, STUDIO_FOLDER) if studio_file else ""
        streaming_link = upload_to_drive(streaming_file, "streaming", now_str, STREAMING_FOLDER) if streaming_file else ""
        subcontrol_link = upload_to_drive(subcontrol_file, "subcontrol", now_str, SUBCONTROL_FOLDER) if subcontrol_file else ""

        # 🔹 Upload foto kendala
        fotos = request.files.getlist("kendala_foto[]")
        folder_links = []
        for i, foto in enumerate(fotos):
            if foto:
                keterangan = data.get("kendala_keterangan[]", [""])[i]
                waktu_input = data.get("kendala_waktu[]", [""])[i]
                waktu_for_name = waktu_input if waktu_input else now_str
                folder_link = upload_to_drive(foto, keterangan or "kendala", waktu_for_name, KENDALA_FOLDER)
                folder_links.append(folder_link)

        folder_link_str = ", ".join(folder_links)

        # 🔹 Simpan ke database
        sql = """
        INSERT INTO laporanx (
            tanggal, nama_td, nama_pdu, nama_tx,
            studio_link, streaming_link, subcontrol_link,
            acara_15, format_15, acara_16, format_16,
            acara_17, format_17, acara_18, format_18,
            kendala, waktu_kendala, link_kendala
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id;
        """
        values = (
            now,
            data.get("petugas_td", [""])[0],
            data.get("petugas_pdu", [""])[0],
            data.get("petugas_transmisi", [""])[0],
            studio_link,
            streaming_link,
            subcontrol_link,
            data.get("acara_15", [""])[0],
            data.get("format_15", [""])[0],
            data.get("acara_16", [""])[0],
            data.get("format_16", [""])[0],
            data.get("acara_17", [""])[0],
            data.get("format_17", [""])[0],
            data.get("acara_18", [""])[0],
            data.get("format_18", [""])[0],
            ", ".join(data.get("kendala_keterangan[]", [])),
            ", ".join(data.get("kendala_waktu[]", [])),
            folder_link_str
        )

        cursor.execute(sql, values)
        last_id = cursor.fetchone()[0]
        db.commit()

        # 🔹 Simpan ke Google Sheets
        sheet.append_row([str(v) for v in values])

        return jsonify({
            "status": "success",
            "message": "Laporan berhasil disimpan!",
            "pdf_url": f"/download_pdf/{last_id}"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/download_pdf/<int:laporan_id>")
def download_pdf(laporan_id):
    cursor.execute("SELECT * FROM laporanx WHERE id=%s", (laporan_id,))
    row = cursor.fetchone()
    if not row:
        return "Laporan tidak ditemukan", 404

    data = {
        "tanggal": row[1],
        "petugas_td": row[2],
        "petugas_pdu": row[3],
        "petugas_transmisi": row[4],
        "bukti_studio": row[5],
        "bukti_streaming": row[6],
        "bukti_subcontrol": row[7],
        "acara_15": row[8], "format_15": row[9],
        "acara_16": row[10], "format_16": row[11],
        "acara_17": row[12], "format_17": row[13],
        "acara_18": row[14], "format_18": row[15],
        "kendala": row[16],
        "waktu_kendala": row[17],
        "link_kendala": row[18],
    }

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("LAPORAN TEKNIS HARIAN", styles["Heading1"]))
    elements.append(Spacer(1, 12))

    identitas = [
        ["Tanggal", str(data["tanggal"])],
        ["Petugas TD", data["petugas_td"]],
        ["Petugas PDU", data["petugas_pdu"]],
        ["Petugas Transmisi", data["petugas_transmisi"]],
    ]
    t1 = Table(identitas, colWidths=[150, 300])
    t1.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, colors.black),
                            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)]))
    elements.append(Paragraph("Step 1: Identitas Petugas", styles["Heading3"]))
    elements.append(t1)
    elements.append(Spacer(1, 12))

    bukti = [
        ["Studio", f'<font color="blue"><u>{data["bukti_studio"]}</u></font>'],
        ["Streaming", f'<font color="blue"><u>{data["bukti_streaming"]}</u></font>'],
        ["Subcontrol", f'<font color="blue"><u>{data["bukti_subcontrol"]}</u></font>'],
    ]
    bukti_rows = [[Paragraph(r[0], styles["Normal"]), Paragraph(r[1], styles["Normal"])] for r in bukti]
    t2 = Table(bukti_rows, colWidths=[150, 300])
    t2.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, colors.black),
                            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey)]))
    elements.append(Paragraph("Step 2: Bukti", styles["Heading3"]))
    elements.append(t2)
    elements.append(Spacer(1, 12))

    acara = [
        ["15.00-15.59", data["acara_15"], data["format_15"]],
        ["16.00-16.59", data["acara_16"], data["format_16"]],
        ["17.00-17.59", data["acara_17"], data["format_17"]],
        ["18.00-18.59", data["acara_18"], data["format_18"]],
    ]
    t3 = Table([["Jam", "Acara", "Format"]] + acara, colWidths=[100, 200, 150])
    t3.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, colors.black),
                            ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
                            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)]))
    elements.append(Paragraph("Step 3: Acara - Acara", styles["Heading3"]))
    elements.append(t3)
    elements.append(Spacer(1, 12))

    kendalas = []
    kets = data["kendala"].split(",") if data["kendala"] else []
    wkt = data["waktu_kendala"].split(",") if data["waktu_kendala"] else []
    lks = data["link_kendala"].split(",") if data["link_kendala"] else []
    for i in range(len(kets)):
        kendalas.append([
            kets[i] if i < len(kets) else "-",
            wkt[i] if i < len(wkt) else "-",
            f'<font color="blue"><u>{lks[i]}</u></font>' if i < len(lks) else "-"
        ])
    if kendalas:
        kendala_rows = [[Paragraph(c, styles["Normal"]) for c in row] for row in kendalas]
        t4 = Table([["Keterangan", "Waktu", "Link"]] + kendala_rows,
                   colWidths=[200, 100, 200])
        t4.setStyle(TableStyle([("BOX", (0,0), (-1,-1), 1, colors.black),
                                ("INNERGRID", (0,0), (-1,-1), 0.5, colors.grey),
                                ("BACKGROUND", (0,0), (-1,0), colors.lightgrey)]))
        elements.append(Paragraph("Step 4: Kendala - Kendala", styles["Heading3"]))
        elements.append(t4)

    doc.build(elements)
    buffer.seek(0)

    return send_file(buffer,
                     as_attachment=True,
                     download_name=f"laporan_{laporan_id}.pdf",
                     mimetype="application/pdf")


if __name__ == "__main__":
    app.run(debug=True)
