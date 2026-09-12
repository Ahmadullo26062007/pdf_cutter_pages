# PDF Cutter — PDF Telefon Optimizer

Juda uzun (cheksiz balandlikdagi) PDF sahifalarini telefonda o'qishga qulay
kichik sahifalarga bo'lib beradigan Flask web-ilova.

Masalan: bitta 20 000 px balandlikdagi skrinshot-PDF — 1400 px'lik
o'nlab oddiy sahifaga aylanadi, rasmlar JPEG'ga siqiladi va natija
hajmi sezilarli kamayadi.

---

## Imkoniyatlar

- Bir vaqtda **bir nechta PDF** yuklash (batch)
- Sahifa balandligini (`chunk_h`) va JPEG sifatini (`quality`) tanlash
- Har bir fayl uchun **real-time progress** (sahifa / foiz)
- Umumiy batch progress-bar
- Tayyor fayllarni **bitta ZIP** qilib yuklab olish
- Ishlov berishdan keyin yuklangan originallar avtomatik o'chiriladi

---

## Texnologiyalar

| Qatlam | Texnologiya |
|---|---|
| Backend | Flask 3 |
| PDF | PyMuPDF (`fitz`) |
| Rasm | Pillow |
| Frontend | HTML + vanilla JS (`templates/index.html`) |
| Parallel ish | `threading` + `Lock` (bir vaqtda 1 batch) |

---

## O'rnatish

```bash
git clone <repo-url>
cd pdf_cutter

python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Ishga tushirish

```bash
python app.py
```

Brauzerda oching: http://127.0.0.1:5000

---

## API

| Metod | Endpoint | Vazifasi |
|---|---|---|
| `GET` | `/` | Asosiy sahifa (UI) |
| `POST` | `/optimize` | PDF fayllarni yuklash va batch'ni boshlash |
| `GET` | `/progress/<batch_id>` | Batch holati va progress (JSON) |
| `GET` | `/download/<batch_id>` | Tayyor natijani ZIP sifatida yuklab olish |

### `POST /optimize`

**Form-data:**

| Maydon | Tur | Default | Chegara |
|---|---|---|---|
| `pdfs` | file[] | — | faqat `.pdf` |
| `chunk_h` | int | `1400` | 500 – 5000 (px) |
| `quality` | int | `80` | 40 – 95 (JPEG) |

**Javob:**

```json
{ "batch_id": "uuid" }
```

### `GET /progress/<batch_id>`

```json
{
  "status": "processing",
  "overall_progress": 42,
  "total_files": 3,
  "zip_status": "waiting",
  "zip": null,
  "error": null,
  "files": {
    "<file_id>": {
      "name": "hujjat.pdf",
      "status": "processing",
      "progress": 60,
      "current_page": 3,
      "total_pages": 5,
      "output_size": 0,
      "error": null
    }
  }
}
```

`status` qiymatlari: `waiting` → `processing` → `done` / `error`

---

## Papkalar tuzilishi

```
pdf_cutter/
├── app.py              # Flask ilova + PDF optimizer logikasi
├── requirements.txt
├── templates/
│   └── index.html      # UI (upload, progress, download)
├── uploads/            # Vaqtinchalik yuklangan PDF'lar (git'da yo'q)
└── outputs/            # Natija PDF'lar va ZIP (git'da yo'q)
```

---

## Qanday ishlaydi

1. Har bir PDF sahifasi PyMuPDF orqali rasmga (pixmap) aylantiriladi.
2. Rasm `chunk_h` balandligidagi bo'laklarga kesiladi.
3. Har bir bo'lak JPEG'ga siqiladi (`quality`).
4. Bo'lak yangi PDF sahifasiga joylanadi (eni 595 pt — A4 kengligi,
   balandligi proporsiya bo'yicha hisoblanadi).
5. Natija `garbage=4, deflate=True, clean=True` bilan saqlanadi.
6. Barcha fayllar tugagach ZIP yig'iladi, originallar o'chiriladi.

---

## Eslatmalar

- Batch holati **xotirada** (`jobs` dict) saqlanadi — server qayta
  ishga tushsa, progress va ZIP havolalari yo'qoladi.
- `processing_lock` sababli bir vaqtda faqat bitta batch ishlanadi,
  qolganlari navbatda turadi.
- `outputs/` papkasi avtomatik tozalanmaydi — vaqti-vaqti bilan
  qo'lda bo'shatib turish kerak.
- Bu development serveri. Production uchun gunicorn/uwsgi + nginx
  ishlatish tavsiya etiladi.
