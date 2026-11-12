# TugasKu – Website Pengumpulan Tugas Kuliah (Python + Flask + SQLite)

## Fitur
- Daftar & login (tiap orang punya akun sendiri; password di-hash, proteksi CSRF)
- Folder per mata kuliah (tugas + file terpisah per folder)
- Upload / unduh file tugas, tandai tugas selesai
- Deadline + notifikasi pengingat (lonceng, toast, dan notifikasi browser)
- Jadwal kuliah per hari (tab Senin–Minggu) + pengingat kuliah 1 jam sebelum mulai
- Tombol cepat ke Absensi Great: https://sso.umc.ac.id/dashboard
- Login SSO (OAuth2) – aktif setelah dikonfigurasi
- Responsif: desktop (sidebar) & mobile (bottom nav), tema gelap/terang, animasi transisi

## Menjalankan
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                   # buka http://localhost:5000
```
Database `tugasku.db` dibuat otomatis. File upload tersimpan di `uploads/<id_user>/<id_matkul>/`.

## Online untuk semua orang
```bash
gunicorn -w 2 -b 0.0.0.0:8000 app:app
```
Di hosting (Render / Railway / VPS / PythonAnywhere) set env `SECRET_KEY` dan `HTTPS=1`.
Pakai volume/disk persisten agar `tugasku.db` dan `uploads/` tidak hilang.

## Mengaktifkan SSO kampus
Login SSO butuh data resmi dari pihak kampus (UPT TIK / admin SSO UMC): client id, secret,
dan URL endpoint OAuth2/OIDC. Daftarkan Redirect URI: `https://DOMAIN-KAMU/sso/callback`. Lalu set:
```
SSO_AUTHORIZE_URL=...   SSO_TOKEN_URL=...   SSO_USERINFO_URL=...
SSO_CLIENT_ID=...       SSO_CLIENT_SECRET=...   SSO_SCOPE="openid profile email"
```
Nama field userinfo (nim, email, name) dapat disesuaikan di fungsi `sso_callback` di `app.py`.
