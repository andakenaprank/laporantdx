# admin_api.py
from flask import Blueprint, request, jsonify, session
from sqlalchemy import text

def create_admin_api(engine, fmt_wib):
    bp = Blueprint("admin_api", __name__)

    @bp.get("/laporan")
    def laporan_filtered():
        # Hanya admin
        if session.get("role") != "admin":
            return jsonify({"error": "Unauthorized"}), 403

        waktu = (request.args.get("waktu") or "").strip().lower()
        # waktu ∈ {pagi, sore, all/''}
        base_sql = """
            SELECT *
            FROM laporanx
            /**WHERE**/
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """

        # pagination sederhana (opsional)
        limit  = max(1, min(int(request.args.get("limit", 200)), 1000))
        offset = max(0, int(request.args.get("offset", 0)))

        params = {"limit": limit, "offset": offset}
        where_sql = ""

        # Filter berdasar token ',pagi}' / ',sore}' pada kolom acara_*
        if waktu in ("pagi", "sore"):
            token = f"%,{waktu}%"
            where_sql = """
            WHERE
              acara_15 ILIKE :tok OR
              acara_16 ILIKE :tok OR
              acara_17 ILIKE :tok OR
              acara_18 ILIKE :tok
            """
            params["tok"] = token

        final_sql = base_sql.replace("/**WHERE**/", where_sql)

        with engine.connect() as conn:
            rows = conn.execute(text(final_sql), params).fetchall()

        data = []
        for r in rows:
            d = dict(r._mapping)
            d["tanggal"] = fmt_wib(d.get("tanggal"))
            d["timestamp_wib"] = fmt_wib(d.get("timestamp_wib"))
            data.append(d)

        return jsonify({"items": data, "limit": limit, "offset": offset})

    return bp
