# RUNBOOK: PEMELIHARAAN DAN SINKRONISASI DATA MATERIAL TEST CERTIFICATE (MTC)

> **Dokumen Resmi Prosedur Pembaruan Data MTC**  
> **Target Pengguna:** Administrator Sistem / Operator Pengganti / Engineer Pengelola Web  
> **Terakhir Diperbarui:** November 2026  
> **Status Dokumen:** Aktif & Terverifikasi

---

## DAFTAR ISI

1. [A. Gambaran Arsitektur & Alur Data](#a-gambaran-arsitektur--alur-data)
2. [B. Persiapan & Persyaratan Lingkungan](#b-persiapan--persyaratan-lingkungan)
3. [C. Prosedur Pembaruan Bulanan (Langkah demi Langkah)](#c-prosedur-pembaruan-bulanan-langkah-demi-langkah)
4. [D. Konversi SQL ke JSON & Validasi Otomatis](#d-konversi-sql-ke-json--validasi-otomatis)
5. [E. Aturan Git & Deployment Cloudflare](#e-aturan-git--deployment-cloudflare)
6. [F. Prosedur Pengujian Pasca-Update (Audit 4 Domain)](#f-prosedur-pengujian-pasca-update-audit-4-domain)
7. [G. Panduan Troubleshooting](#g-panduan-troubleshooting)
8. [H. Prosedur Rollback Cepat](#h-prosedur-rollback-cepat)
9. [I. Checklist Bulanan Administrator](#i-checklist-bulanan-administrator)

---

## A. GAMBARAN ARSITEKTUR & ALUR DATA

Sistem verifikasi Material Test Certificate (MTC 3.1) menggunakan arsitektur statis terisolasi (*air-gapped static dataset*) untuk menjamin keamanan maksimal database internal perusahaan.

### Diagram Alur Data:

```
+-------------------------------------------------------------------------+
| [INTERNAL PERUSAHAAN]                                                   |
| Database Internal QC (Laravel QCDB MySQL)                               |
+-------------------------------------------------------------------------+
                                    |
                                    v (Export manual bulanan oleh QA/Admin)
+-------------------------------------------------------------------------+
| File SQL Mentah: C:\laragon\www\peroni-group\data-sql\database mc.sql   |
| (BERADA DI LUAR GIT REPOSITORY - TIDAK PERNAH DIUNGGAH KE GITHUB)       |
+-------------------------------------------------------------------------+
                                    |
                                    v (Ekstraksi & Sanitasi: convert-sql-to-json.py)
+-------------------------------------------------------------------------+
| Dataset Publik: peroniks\data\certificates-demo.json                    |
| - Hanya sertifikat status APPROVED                                      |
| - Filter data sensitif: TANPA Customer, PO, Harga, User, Password, PII  |
+-------------------------------------------------------------------------+
                                    |
                                    v (Audit Otomatis: validate-mtc-data.py)
+-------------------------------------------------------------------------+
| [GERBANG VALIDASI: 9 CHECKLIST MUTLAK HARUS PASS]                       |
+-------------------------------------------------------------------------+
                                    |
                                    v (Git Commit & Push ke GitHub)
+-------------------------------------------------------------------------+
| Repository GitHub: peroniks (Branch main)                               |
+-------------------------------------------------------------------------+
                                    |
                                    v (Otomatis via Cloudflare Workers Builds)
+-------------------------------------------------------------------------+
| [WEBSITE PUBLIK]                                                        |
| 1. https://peroni-group.com/mc/                                         |
| 2. https://flange-indonesia.com/mc/                                     |
| 3. https://fitting-indonesia.com/mc/                                    |
| 4. https://valve-indonesia.com/mc/                                      |
+-------------------------------------------------------------------------+
```

### Prinsip Keamanan Utama:
1. **Zero Database Exposure:** Database MySQL internal tidak pernah dibuka ke publik atau dihubungkan langsung ke Cloudflare Workers.
2. **Sanitasi Total:** Informasi komersial (nama pemesan, nomor PO, harga, akun user QC, IP audit) dihapus secara permanen pada tahap konversi. Publik hanya menerima data verifikasi mutu material (Heat Number, Certificate Number, Grade, Komposisi Kimia, dan Sifat Mekanik).
3. **Repository Cleanliness:** File SQL internal dan dump backup **dilarang keras** masuk ke staging maupun commit Git.

---

## B. PERSIAPAN & PERSYARATAN LINGKUNGAN

Sebelum memulai pembaruan bulanan, pastikan Anda berada di komputer kerja yang telah memiliki konfigurasi berikut:

### 1. Struktur Folder Kerja:
- **Folder Induk:** `C:\laragon\www\peroni-group\`
- **Lokasi SQL Internal:** `C:\laragon\www\peroni-group\data-sql\database mc.sql` (di luar repositori Git)
- **Git Repository Root:** `C:\laragon\www\peroni-group\peroniks\`
- **Dataset JSON Publik:** `C:\laragon\www\peroni-group\peroniks\data\certificates-demo.json`
- **Script Pemeliharaan:** `C:\laragon\www\peroni-group\peroniks\scripts\`

### 2. Software yang Dibutuhkan:
- **PowerShell** (Windows PowerShell atau PowerShell 7)
- **Python 3.10+** (telah terpasang pada path sistem) dengan modul bawaan `sqlite3` dan `json`
- **Node.js 18+ / 20+** dan **npm**
- **Git for Windows**

### 3. Akses yang Diperlukan:
- Akses baca ke file SQL export bulanan dari tim QA/QC.
- Izin push Git ke remote repository GitHub `peroniks` (branch `main`).
- Akses monitoring dashboard Cloudflare Pages / Workers Builds.

> [!CAUTION]
> **Pemberitahuan Kredensial:** Jangan pernah mencatat password, access token GitHub, atau API key Cloudflare di dalam file repositori maupun file teks lokal.

---

## C. PROSEDUR PEMBARUAN BULANAN (LANGKAH DEMI LANGKAH)

Jalankan prosedur berikut setiap kali menerima file database SQL terbaru dari tim QC (biasanya di awal atau akhir bulan):

### Langkah 1: Tempatkan File SQL Terbaru
Salin file export SQL terbaru ke lokasi standar:
```
C:\laragon\www\peroni-group\data-sql\database mc.sql
```
*Pastikan nama file persis `database mc.sql` (atau gunakan parameter lokasi manual jika berbeda).*

### Langkah 2: Buka Terminal PowerShell
Buka PowerShell dan masuk ke direktori proyek `peroniks`:
```powershell
cd C:\laragon\www\peroni-group\peroniks
```

### Langkah 3: Periksa Kebersihan Git Terlebih Dahulu
Pastikan tidak ada perubahan liar sebelum konversi:
```powershell
git status --short
```
*Hasil ideal: bersih atau hanya modifikasi yang Anda rencanakan.*

---

## D. KONVERSI SQL KE JSON & VALIDASI OTOMATIS (STAGING WORKFLOW)

Untuk menjamin dataset produksi aktif tidak pernah tersentuh sebelum dinyatakan valid, konversi dilakukan ke file penampung (*staging file*).

### Langkah 4: Jalankan Konversi ke File Staging
Eksekusi script konversi dengan mengarahkan output ke file staging `data/certificates-demo.staging.json`:

```powershell
python scripts/convert-sql-to-json.py "C:\laragon\www\peroni-group\data-sql\database mc.sql" "data/certificates-demo.staging.json"
if ($LASTEXITCODE -ne 0) { throw "CRITICAL: Konversi SQL ke staging gagal! Proses dihentikan." }
```

**Output yang diharapkan:**
```text
[*] Starting MTC SQL to JSON conversion...
[*] Source SQL: C:\laragon\www\peroni-group\data-sql\database mc.sql
[*] Target JSON: data/certificates-demo.staging.json
[*] Imported 125 relevant table statements into in-memory database in 0.17s
[*] Extracted 7256 verified certificates.
[+] SUCCESS: Exported 7256 records to data/certificates-demo.staging.json (4.69 MB) in 0.51s
```

### Langkah 5: Jalankan Script Validasi pada File Staging (Wajib 10/10 PASS!)
Jalankan script validasi integritas data langsung pada file staging:

```powershell
python scripts/validate-mtc-data.py "data/certificates-demo.staging.json"
if ($LASTEXITCODE -ne 0) {
    Remove-Item "data/certificates-demo.staging.json" -Force -ErrorAction SilentlyContinue
    throw "CRITICAL: Validasi data staging GAGAL! File staging tidak valid dan telah dibuang."
}
```

**Kriteria Lulus Validasi (10/10 PASS):**
```text
======================================================================
MTC DATASET PRE-PUBLISHING AUDIT & VALIDATION
======================================================================
Target JSON File: data/certificates-demo.staging.json

CHECK ITEM                       | STATUS | DETAILS
---------------------------------------------------------------------------
1. JSON Parsing                  | PASS   | Valid JSON, parsed successfully
2. Record Count                  | PASS   | 7256 records found (>= 3,000 threshold)
3A. Schema Allowlist             | PASS   | 100% records conform strictly to allowed root and chemical fields
3B. Required Fields              | PASS   | All required fields present and non-empty across all records
4. Approval Status               | PASS   | All records have status = 'APPROVED'
5. Unit Standard                 | PASS   | Engineering units formatted correctly (MPa, HB)
6. Certificate Uniqueness        | PASS   | 7256 certificates, 0 duplicates
7. PII / Data Privacy            | PASS   | Zero customer names, POs, pricing, or internal PII keys
8. Benchmark Heat A204102609     | PASS   | All verified traits match QC/2026/10/101 exactly
9. Git SQL Security              | PASS   | No SQL files tracked in Git repository
---------------------------------------------------------------------------
[+] FINAL RESULT: ALL CHECKS PASSED. Dataset is READY for publication.
======================================================================
```

> [!NOTE]
> **Catatan Pertumbuhan Dataset:**  
> Baseline dataset pada Oktober 2026 adalah 6.222 record. Pada dump SQL November 2026, dataset bertambah menjadi 7.256 record (+1.034 record baru). Pertambahan ini berasal dari batch produksi dan sertifikat baru yang di-approve oleh QA antara 8 Oktober 2026 hingga 21 November 2026.

> [!WARNING]
> **STOP JIKA ADA STATUS FAIL!**  
> Jika terdapat satu saja item `FAIL` (misalnya ditemukan field asing di luar allowlist atau ada PII), script langsung melempar exit code 1 dan membatalkan proses.

---

## E. PROMOSI DATASET ATOMIK & ATURAN GIT DEPLOYMENT

### Langkah 6: Promosi Aman Dataset dengan Atomic Replacement
Gunakan method .NET `[System.IO.File]::Replace()` pada Windows NTFS untuk menggantikan dataset produksi secara atomik sekaligus membuat backup bertimestamp:

```powershell
# 1. Pastikan file staging tersedia dan berukuran wajar (> 1 MB)
$stagingFile = "C:\laragon\www\peroni-group\peroniks\data\certificates-demo.staging.json"
$prodFile    = "C:\laragon\www\peroni-group\peroniks\data\certificates-demo.json"

if (-not (Test-Path $stagingFile) -or (Get-Item $stagingFile).Length -lt 1000000) {
    throw "CRITICAL: File staging tidak ditemukan atau ukurannya tidak valid!"
}

# 2. Buat nama backup bertimestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupFile = "C:\laragon\www\peroni-group\peroniks\data\certificates-demo.backup.$timestamp.json"

# 3. Lakukan atomic replacement (staging -> prod, dan prod lama -> backup)
Write-Host "Melakukan atomic dataset replacement..." -ForegroundColor Cyan
[System.IO.File]::Replace($stagingFile, $prodFile, $backupFile)
Write-Host "SUKSES: Dataset aktif diperbarui. Backup lama tersimpan di: $backupFile" -ForegroundColor Green
```

### Langkah 7: Validasi Ulang Dataset Produksi Aktif
Pastikan dataset produksi yang baru terpasang tetap valid:
```powershell
python scripts/validate-mtc-data.py "data/certificates-demo.json"
if ($LASTEXITCODE -ne 0) {
    Write-Error "CRITICAL: Validasi dataset produksi pasca-promosi GAGAL! Melakukan rollback otomatis..."
    Copy-Item $backupFile -Destination $prodFile -Force
    throw "Dataset telah di-rollback ke versi sebelumnya."
}
```

### Langkah 8: Git Security Gate (Pemeriksaan Staging)
Stage dataset dan lakukan verifikasi ketat pada Git index:

```powershell
# 1. Stage HANYA file dataset produksi
git add data/certificates-demo.json

# 2. Periksa apakah ada file selain dataset di staging (Security Gate)
$staged = git diff --cached --name-only
$unexpected = $staged | Where-Object { $_ -ne "data/certificates-demo.json" }
if ($unexpected) {
    throw "CRITICAL SECURITY ALERT: Ditemukan file selain data/certificates-demo.json di Git staging:`n$($unexpected -join "`n")`nProses dihentikan. Harap periksa manual!"
}

# 3. Pastikan tidak ada file SQL yang terlacak
$trackedSql = git ls-files "*.sql" "*.SQL"
if ($trackedSql) {
    throw "CRITICAL SECURITY ALERT: File SQL terdeteksi di Git index: $trackedSql"
}

# 4. Tampilkan status dan statistik diff untuk inspeksi visual
git status --short
git diff --cached --stat
```

### Langkah 9: Persetujuan Administrator & Publikasi Git
Setelah seluruh pemeriksaan di atas lulus, **mintalah persetujuan administrator** sebelum melakukan commit dan push:

```powershell
# Jalankan HANYA setelah disetujui administrator:
git commit -m "data(mtc): update monthly verification records from QCDB"
git push peroni main
```

### Langkah 10: Pantau Deployment Cloudflare
Setelah di-push ke remote `peroni` pada branch `main`, Cloudflare Workers Builds akan otomatis mengompilasi halaman statis. Pantau dashboard Cloudflare hingga status: `Success` (Hijau).

---

## F. PROSEDUR PENGUJIAN PASCA-UPDATE (AUDIT 4 DOMAIN)

Setelah Cloudflare selesai melakukan deployment, lakukan uji verifikasi langsung menggunakan browser.

### 1. Data Acuan Benchmark:
Gunakan sertifikat uji benchmark wajib:
- **Heat Number:** `A204102609`
- **Certificate Number:** `QC/2026/10/101`
- **Material Grade:** `1.4308`
- **Specification:** `BS EN 10213`
- **Yield Strength:** `251.86 MPa`
- **Tensile Strength:** `502.91 MPa`
- **Hardness:** `168.00 HB`
- **Status:** `APPROVED`
- **Chemical Analysis:** Cr: `18.26%`, Ni: `8.16%`, Mo: `0.14%`, C: `0.038%`

### 2. URL Pengujian Langsung:
Buka masing-masing URL portal berikut pada browser:

1. **Portal Utama Peroni Group:**  
   [https://peroni-group.com/mc/?heat=A204102609](https://peroni-group.com/mc/?heat=A204102609)
2. **Portal Flange Indonesia:**  
   [https://flange-indonesia.com/mc/?heat=A204102609](https://flange-indonesia.com/mc/?heat=A204102609)
3. **Portal Fitting Indonesia:**  
   [https://fitting-indonesia.com/mc/?heat=A204102609](https://fitting-indonesia.com/mc/?heat=A204102609)
4. **Portal Valve Indonesia:**  
   [https://valve-indonesia.com/mc/?heat=A204102609](https://valve-indonesia.com/mc/?heat=A204102609)

### 3. Elemen yang Wajib Divalidasi di Halaman Web:
- [x] Lencana **"MATERIAL DATA VERIFIED - Electronic Quality Inspection Record"** tampil berwarna hijau.
- [x] Nilai Certificate Number dan Heat Number cocok.
- [x] Tabel **Chemical Composition Summary** menampilkan seluruh unsur.
- [x] Tabel **Mechanical Properties Summary** menampilkan Yield, Tensile, dan Hardness.
- [x] Tombol **"Download MTC PDF"** berfungsi dan membuka berkas PDF A4 resmi dengan data yang identik.

---

## G. PANDUAN TROUBLESHOOTING

| Masalah / Error | Penyebab | Solusi |
|---|---|---|
| `FileNotFoundError: Source SQL file not found` | File `database mc.sql` belum diletakkan di `peroni-group\data-sql\` atau salah penamaan file. | Pastikan file bernama `database mc.sql` berada di folder `C:\laragon\www\peroni-group\data-sql\`. |
| `Record Count FAIL (< 3000)` | File SQL terpotong saat export dari phpMyAdmin atau database internal belum selesai di-dump. | Mintalah export ulang file SQL lengkap dari tim QC dan periksa ukuran file (normalnya > 10 MB). |
| `Benchmark Heat A204102609 FAIL` | Record referensi tidak ditemukan atau nilainya berubah di database internal. | Periksa apakah sample `A204102609` berstatus non-APPROVED atau terhapus di database internal. |
| `PII / Data Privacy FAIL` | Terdapat field internal baru yang tidak disaring oleh script konversi. | Pastikan query ekstraksi pada `convert-sql-to-json.py` hanya memilih kolom resmi verifikasi teknis. |
| `Cloudflare Build Failed (Webpack / Memory)` | File JSON rusak atau terjadi sintaks error saat parsing. | Jalankan `npm run build` lokal di PowerShell untuk melihat log error sebelum push ke remote. |
| `Git Push Gagal (Authentication)` | Sesi GitHub Personal Access Token kadaluarsa. | Perbarui Personal Access Token di Git Credential Manager Windows. |
| `Tombol Download PDF tidak merespon di browser` | Pop-up blocker browser memblokir tab baru atau browser gagal merender blob. | Buka browser console (F12) untuk melihat error dan pastikan pop-up diizinkan. |

---

## H. PROSEDUR ROLLBACK CEPAT

Jika ditemukan kendala pada dataset yang baru dipromosikan, pemulihan (*rollback*) dapat dilakukan dalam hitungan detik:

### Opsi 1: Rollback Lokal Menggunakan File Backup Bertimestamp
Jika masalah terdeteksi sebelum push:
```powershell
# Temukan berkas backup terakhir yang dibuat oleh [System.IO.File]::Replace()
$latestBackup = Get-ChildItem "data/certificates-demo.backup.*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

if ($latestBackup) {
    Write-Host "Memulihkan dataset dari backup: $($latestBackup.FullName)..." -ForegroundColor Yellow
    Copy-Item $latestBackup.FullName -Destination "data/certificates-demo.json" -Force
    Write-Host "SUKSES: Dataset aktif telah dikembalikan ke kondisi sebelumnya." -ForegroundColor Green
} else {
    # Alternatif pemulihan langsung dari Git commit terakhir
    git checkout HEAD -- data/certificates-demo.json
}
```

### Opsi 2: Rollback Commit (Jika Sudah Terlanjur di-Push ke Remote)
Jika commit yang bermasalah sudah terlanjur di-push ke GitHub:
```powershell
# Buat commit pembalik (revert) secara bersih
git revert HEAD --no-edit

# Push commit revert ke remote peroni
git push peroni main
```
Cloudflare akan otomatis mendeteksi revert commit dan me-redeploy dataset versi sebelumnya yang stabil.

---

## I. CHECKLIST BULANAN ADMINISTRATOR

Gunakan checklist ini sebagai panduan cepat setiap kali melakukan siklus pembaruan:

```markdown
[ ] 1. File SQL terbaru diterima dan disimpan di `data-sql/database mc.sql`.
[ ] 2. Masuk ke folder `C:\laragon\www\peroni-group\peroniks`.
[ ] 3. Jalankan konversi ke staging: `python scripts/convert-sql-to-json.py "C:\laragon\www\peroni-group\data-sql\database mc.sql" "data/certificates-demo.staging.json"`.
[ ] 4. Jalankan validasi staging: `python scripts/validate-mtc-data.py "data/certificates-demo.staging.json"` dan pastikan 10/10 PASS (termasuk 3A Schema Allowlist).
[ ] 5. Promosikan staging secara atomik dengan backup bertimestamp via `[System.IO.File]::Replace()`.
[ ] 6. Validasi ulang dataset produksi aktif: `python scripts/validate-mtc-data.py "data/certificates-demo.json"`.
[ ] 7. Stage dataset: `git add data/certificates-demo.json`.
[ ] 8. Verifikasi Git Security Gate: `git diff --cached --name-only` (pastikan HANYA `data/certificates-demo.json` yang ada di staging).
[ ] 9. Pastikan `git ls-files "*.sql"` bernilai KOSONG.
[ ] 10. Minta persetujuan administrator untuk publikasi.
[ ] 11. Setelah disetujui, jalankan: `git commit -m "data(mtc): update monthly verification records from QCDB"`.
[ ] 12. Kirim ke remote `peroni`: `git push peroni main`.
[ ] 13. Pantau dashboard Cloudflare Workers Builds hingga status "Success".
[ ] 14. Uji verifikasi Heat Number A204102609 di browser dan uji unduh PDF MTC.
```

---
*Dokumen ini dirancang sebagai acuan baku dan mandiri untuk pengelola teknis website Peroni Group.*
