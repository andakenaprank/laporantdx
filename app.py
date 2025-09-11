from flask import Flask, render_template, request, jsonify, send_file
import os, io, json
import psycopg2
import gspread
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
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
    # Render: ambil dari environment variable
    creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
else:
    # Lokal: pakai file google_creds.json
    creds = ServiceAccountCredentials.from_json_keyfile_name("google_creds.json", scope)

client = gspread.authorize(creds)
sheet = client.open_by_key("10u7E3c_IA5irWT0XaKb4eb10taOocH1Q9BK7UrlccDU").sheet1


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.form.to_dict(flat=False)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
            data.get("bukti_studio", [""])[0],
            data.get("bukti_streaming", [""])[0],
            data.get("bukti_subcontrol", [""])[0],
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
            ", ".join(data.get("kendala_bukti[]", []))
        )

        cursor.execute(sql, values)
        last_id = cursor.fetchone()[0]
        db.commit()

        # 🔹 Simpan ke Google Sheets
        sheet.append_row(list(values))

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

    # 🔹 mapping kolom
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

    # 🔹 Generate PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("LAPORAN TEKNIS HARIAN", styles["Heading1"]))
    elements.append(Spacer(1, 12))

    identitas = [
        ["Tanggal", data["tanggal"]],
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
