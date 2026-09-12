from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file
)

from pathlib import Path
from PIL import Image
import fitz
import io
import uuid
import threading
import zipfile
import shutil
import time


app = Flask(__name__)

# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Bitta umumiy batch
jobs = {}

# Bir vaqtning o'zida faqat BITTA batch ishlaydi.
# Ichidagi PDFlar navbat bilan ishlanadi.
processing_lock = threading.Lock()


# --------------------------------------------------
# PDF OPTIMIZER
# --------------------------------------------------

def optimize_pdf(
    input_path,
    output_path,
    chunk_h,
    quality,
    progress_callback
):
    """
    Juda uzun PDF sahifalarini kichik sahifalarga bo'ladi.
    """

    doc = None
    outdoc = None

    try:

        doc = fitz.open(str(input_path))
        outdoc = fitz.open()

        total_pages = len(doc)

        for page_number, page in enumerate(
            doc,
            start=1
        ):

            # PDF sahifasini rasmga aylantiramiz
            pix = page.get_pixmap(
                matrix=fitz.Matrix(1.0, 1.0),
                alpha=False
            )

            img = Image.frombytes(
                "RGB",
                [pix.width, pix.height],
                pix.samples
            )

            # Juda uzun sahifani bo'laklarga ajratish
            for top in range(
                0,
                img.height,
                chunk_h
            ):

                bottom = min(
                    top + chunk_h,
                    img.height
                )

                chunk = img.crop(
                    (
                        0,
                        top,
                        img.width,
                        bottom
                    )
                )

                # JPEG compression
                buffer = io.BytesIO()

                chunk.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    optimize=True
                )

                jpg_data = buffer.getvalue()

                # Sahifa proporsiyasi
                page_width = 595

                page_height = (
                    page_width
                    * chunk.height
                    / chunk.width
                )

                new_page = outdoc.new_page(
                    width=page_width,
                    height=page_height
                )

                new_page.insert_image(
                    new_page.rect,
                    stream=jpg_data
                )

            # PDF progress
            page_progress = (
                page_number /
                total_pages
                * 100
            )

            progress_callback(
                page_number,
                total_pages,
                page_progress
            )

        # Saqlash
        outdoc.save(
            str(output_path),
            garbage=4,
            deflate=True,
            clean=True
        )

        return True, None

    except Exception as e:

        return False, str(e)

    finally:

        if outdoc:
            outdoc.close()

        if doc:
            doc.close()


# --------------------------------------------------
# BATCH PROCESSOR
# --------------------------------------------------

def process_batch(
    batch_id,
    files,
    chunk_h,
    quality
):

    batch = jobs[batch_id]

    try:

        # Boshqa batch bilan bir vaqtda ishlamasin
        with processing_lock:

            total_files = len(files)

            batch["status"] = "processing"
            batch["total_files"] = total_files

            for index, file_info in enumerate(
                files
            ):

                file_id = file_info["id"]
                input_path = Path(
                    file_info["input"]
                )
                output_path = Path(
                    file_info["output"]
                )

                item = batch["files"][file_id]

                item["status"] = "processing"
                item["progress"] = 0
                item["current_page"] = 0
                item["total_pages"] = 0

                # Callback
                def update_progress(
                    current_page,
                    total_pages,
                    progress
                ):

                    item["current_page"] = (
                        current_page
                    )

                    item["total_pages"] = (
                        total_pages
                    )

                    item["progress"] = round(
                        progress
                    )

                    # Umumiy batch progress
                    completed_before = index

                    current_fraction = (
                        progress / 100
                    )

                    overall = (
                        (
                            completed_before
                            + current_fraction
                        )
                        / total_files
                        * 100
                    )

                    batch["overall_progress"] = round(
                        overall
                    )

                success, error = optimize_pdf(
                    input_path,
                    output_path,
                    chunk_h,
                    quality,
                    update_progress
                )

                if success:

                    item["status"] = "done"
                    item["progress"] = 100
                    item["current_page"] = (
                        item["total_pages"]
                    )

                    try:
                        item["output_size"] = (
                            output_path.stat().st_size
                        )
                    except Exception:
                        item["output_size"] = 0

                else:

                    item["status"] = "error"
                    item["error"] = error

                # Keyingi fayl oldidan
                batch["overall_progress"] = round(
                    (
                        (index + 1)
                        / total_files
                        * 100
                    )
                )

            # ZIP yaratish
            batch["zip_status"] = "processing"

            zip_path = (
                OUTPUT_DIR
                / f"pdf_optimizer_{batch_id}.zip"
            )

            with zipfile.ZipFile(
                zip_path,
                "w",
                zipfile.ZIP_DEFLATED
            ) as zip_file:

                for file_info in files:

                    item = batch["files"][
                        file_info["id"]
                    ]

                    if item["status"] != "done":
                        continue

                    output_path = Path(
                        file_info["output"]
                    )

                    if output_path.exists():

                        zip_file.write(
                            output_path,
                            arcname=output_path.name
                        )

            batch["zip"] = str(zip_path)
            batch["zip_status"] = "done"

            batch["status"] = "done"
            batch["overall_progress"] = 100

            # Original uploadlarni o'chirish
            for file_info in files:

                try:
                    Path(
                        file_info["input"]
                    ).unlink(
                        missing_ok=True
                    )
                except Exception:
                    pass

    except Exception as e:

        batch["status"] = "error"
        batch["error"] = str(e)


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# --------------------------------------------------
# START BATCH
# --------------------------------------------------

@app.route(
    "/optimize",
    methods=["POST"]
)
def start_optimization():

    uploaded_files = request.files.getlist(
        "pdfs"
    )

    if not uploaded_files:

        return jsonify({
            "error":
                "PDF fayllar tanlanmagan."
        }), 400

    # Faqat PDF
    valid_files = []

    for file in uploaded_files:

        if not file.filename:
            continue

        if not file.filename.lower().endswith(
            ".pdf"
        ):
            continue

        valid_files.append(file)

    if not valid_files:

        return jsonify({
            "error":
                "PDF fayl topilmadi."
        }), 400

    # Parametrlar
    try:

        chunk_h = int(
            request.form.get(
                "chunk_h",
                1400
            )
        )

        quality = int(
            request.form.get(
                "quality",
                80
            )
        )

    except ValueError:

        return jsonify({
            "error":
                "Parametrlar noto'g'ri."
        }), 400

    # Chegaralar
    chunk_h = max(
        500,
        min(chunk_h, 5000)
    )

    quality = max(
        40,
        min(quality, 95)
    )

    batch_id = str(
        uuid.uuid4()
    )

    files = []

    for file in valid_files:

        file_id = str(
            uuid.uuid4()
        )

        original_name = Path(
            file.filename
        ).stem

        safe_name = (
            f"{file_id}_"
            f"{file.filename}"
        )

        input_path = (
            UPLOAD_DIR
            / safe_name
        )

        output_path = (
            OUTPUT_DIR
            / f"{original_name}_telefon.pdf"
        )

        file.save(
            input_path
        )

        files.append({
            "id": file_id,
            "input": str(input_path),
            "output": str(output_path),
            "name": file.filename
        })

    # Batch
    jobs[batch_id] = {

        "status":
            "waiting",

        "overall_progress":
            0,

        "total_files":
            len(files),

        "zip":
            None,

        "zip_status":
            "waiting",

        "error":
            None,

        "files": {}

    }

    # Har bir faylni UI uchun saqlash
    for file_info in files:

        jobs[batch_id]["files"][
            file_info["id"]
        ] = {

            "id":
                file_info["id"],

            "name":
                file_info["name"],

            "status":
                "waiting",

            "progress":
                0,

            "current_page":
                0,

            "total_pages":
                0,

            "output_size":
                0,

            "error":
                None

        }

    # Background
    thread = threading.Thread(
        target=process_batch,
        args=(
            batch_id,
            files,
            chunk_h,
            quality
        ),
        daemon=True
    )

    thread.start()

    return jsonify({
        "batch_id":
            batch_id
    })


# --------------------------------------------------
# PROGRESS
# --------------------------------------------------

@app.route(
    "/progress/<batch_id>"
)
def get_progress(batch_id):

    batch = jobs.get(
        batch_id
    )

    if not batch:

        return jsonify({
            "error":
                "Batch topilmadi."
        }), 404

    return jsonify(batch)


# --------------------------------------------------
# DOWNLOAD ZIP
# --------------------------------------------------

@app.route(
    "/download/<batch_id>"
)
def download_zip(batch_id):

    batch = jobs.get(
        batch_id
    )

    if not batch:

        return "Batch topilmadi", 404

    if batch["status"] != "done":

        return (
            "Batch hali tayyor emas",
            400
        )

    zip_path = Path(
        batch["zip"]
    )

    if not zip_path.exists():

        return (
            "ZIP fayl topilmadi",
            404
        )

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=zip_path.name,
        mimetype="application/zip"
    )


# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == "__main__":

    print()
    print("=" * 55)
    print("        PDF TELEFON OPTIMIZER")
    print("=" * 55)
    print()
    print(
        "Brauzerda oching:"
    )
    print(
        "http://127.0.0.1:5000"
    )
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )
