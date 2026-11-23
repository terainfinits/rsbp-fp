# CodeKG

CodeKG membuat peta kode Python yang dapat dikueri agen dari terminal. Satu build menghasilkan graf RDF dalam Turtle dan penjelajah HTML offline di `codekg-out/` milik proyek yang diindeks. Pertanyaan demo adalah **“Jika `verify_token` berubah, siapa pemanggil langsungnya dan di baris mana saya harus memeriksa kode?”**

## Mulai dari PowerShell

Gunakan Python 3.10 atau lebih baru. Buka PowerShell di direktori yang berisi `pyproject.toml`. Instalasi pertama membutuhkan paket Python dari pip atau cache lokal. Build, kueri, dan visualisasi berjalan offline.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
$kg = (Resolve-Path .\.venv\Scripts\codekg.exe).Path
& $kg build .\demo
& $kg find verify_token --root .\demo
Start-Process .\demo\codekg-out\graph.html
```

Variabel `$kg` menunjuk executable sehingga aktivasi venv tidak diperlukan. Di terminal baru cukup tetapkan kembali `$kg`. Jika venv sudah aktif, perintah dapat ditulis langsung sebagai `codekg`.

## Dari pertanyaan agen ke bukti kode

Jalankan dari root repositori setelah build. `--root` memilih workspace yang diindeks. Tanpa opsi tersebut CLI menggunakan direktori kerja. File kueri dibaca relatif terhadap direktori kerja terminal.

```powershell
$target = (& $kg find verify_token --root demo | ConvertFrom-Json)[0]
$target | Select-Object qualified, path, line
$hits = & $kg callers $target.id --root demo | ConvertFrom-Json
$hits | Select-Object qualified, sitePath, siteLine
$login = ($hits | Where-Object name -eq 'login')[0]
& $kg callees $login.id --root demo
& $kg query .\queries\verify_callers.rq --root demo

$hits | ForEach-Object {
    $file = Join-Path .\demo $_.sitePath
    '{0}:{1}  {2}' -f $_.sitePath, $_.siteLine, (Get-Content $file)[$_.siteLine - 1].Trim()
}
```

Definisi berada di `auth/tokens.py:4`. Ada **dua pemanggil dan tiga lokasi panggilan** dalam `app/service.py`. Method `SessionStore.save` memanggil alias `check` di baris 6. Fungsi async `login` memakai alias yang sama di baris 10 dan 12. Agen dapat langsung membuka ketiga baris tersebut. Di baris 16, `dispatch` memilih fungsi melalui `handlers[action]` saat runtime. Graf menyimpan ekspresi ini dengan status `unresolved`.

Di HTML, klik file `service.py` untuk membuka deklarasinya, atau cari `verify_token` dan pilih hasilnya. Pilih relasi `login → calls → verify_token` untuk melihat kedua lokasi bukti. Filter tipe `Method` menampilkan dua method `save`. Tombol **Struktur workspace** mengembalikan tampilan awal.

## Antarmuka untuk agen

| Perintah | Jawaban |
|---|---|
| `build <root>` | Ringkasan jumlah file dan simbol, jumlah ekspresi panggilan per status, serta daftar file gagal diparse dan alasannya. Build penuh mengganti hasil lama. |
| `find <teks>` | Kandidat dari nama, nama lengkap, dan path. Kecocokan persis ditempatkan lebih dulu. Gunakan ID dari hasil untuk kueri lanjut. |
| `members <id>` | Isi langsung folder atau deklarasi langsung file, class, maupun fungsi. |
| `callers <id>`, `callees <id>` | Satu baris hasil per lokasi panggilan langsung. `line` dan `endLine` menunjuk definisi simbol hasil. `sitePath` dan `siteLine` menunjuk ekspresi panggilannya. |
| `query <file.rq>` | Hasil SPARQL SELECT atas indeks lokal sebagai array objek JSON. Setiap objek memakai nama variabel SELECT sebagai kunci. |

Hasil tersedia sebagai JSON pada stdout. Kesalahan perintah dikirim ke stderr dengan status keluar berbeda dari nol. Nomor baris dimulai dari 1. `siteColumn` mengikuti offset byte UTF-8 AST Python yang dimulai dari 0. Contoh petunjuk untuk loop agen ada di [demo/AGENTS.md](demo/AGENTS.md). Setelah mengedit, menghapus, atau mengganti nama simbol, jalankan build ulang sebelum kueri berikutnya.

## Representasi pengetahuan

Inventarisasi mengikuti aturan `.gitignore` bertingkat di bawah root pemindaian dan melewati symlink, virtual environment, cache, serta folder hasil. Semua file yang lolos mendapat simpul. Lintasan AST pertama mengumpulkan lingkup dan deklarasi. Lintasan kedua mencocokkan impor, pewarisan, serta target panggilan. RDFLib menyimpan fakta dan menjalankan kueri. HTML dibuat dari graf RDF yang sama.

Kosakata ada di namespace `urn:codekg:vocab:`. Tipe entitasnya adalah `Folder`, `File`, `Class`, `Function`, `Method`, dan `Constant`. `Method` merupakan subkelas `Function` dalam skema. `Constant` mewakili deklarasi tingkat modul dengan konvensi nama huruf kapital. Identitas entitas berasal dari jenis, path relatif, dan nama dalam lingkupnya. Penambahan baris kosong mempertahankan ID simbol. Setiap lokasi pemanggilan memiliki simpul bukti tersendiri bertipe `CallSite`.

| Relasi | Makna A → B |
|---|---|
| `contains` | Folder A langsung berisi folder atau file B. |
| `declares` | File, class, atau fungsi A mendeklarasikan simbol B. |
| `imports` | Lingkup A mengimpor modul internal yang direpresentasikan file B. |
| `inheritsFrom` | Class A mencantumkan class internal B sebagai basis yang dapat diidentifikasi. |
| `calls` | Dalam lingkup A terdapat ekspresi pemanggilan dengan target statis B. Panggilan konstruktor menunjuk class. |

Satu triple nyata dari demo, ditulis kembali dengan prefiks yang sama:

```turtle
@prefix kg: <urn:codekg:vocab:> .
<urn:codekg:symbol:app/service.py:login> kg:calls <urn:codekg:symbol:auth/tokens.py:verify_token> .
```

Sisi tersebut merangkum dua ekspresi di dalam `login`. Kueri [verify_callers.rq](queries/verify_callers.rq) membaca simpul `CallSite` melalui `kg:caller` dan `kg:target`, mengambil path dan nomor baris, lalu menyaring bukti lintas file. Untuk memeriksa bagian yang memerlukan peninjauan manual, simpan kueri berikut sebagai file `.rq` lalu jalankan perintah `query`.

```sparql
PREFIX kg: <urn:codekg:vocab:>
SELECT ?path ?line ?expression WHERE {
  ?site a kg:CallSite ; kg:status "unresolved" ;
        kg:path ?path ; kg:line ?line ; kg:expression ?expression .
}
ORDER BY ?path ?line
```

### Pilihan untuk tugas KBE

| Pilihan | Bagaimana menjawab “siapa yang memanggil fungsi X?” |
|---|---|
| Propositional logic | Setiap pasangan memerlukan proposisi seperti `LoginMemanggilVerifyToken`. Sistem harus mengelola pemetaan pasangan secara terpisah untuk pencarian target sembarang. |
| First-order logic | Predikat `Calls(p, x)` dapat menyatakan pertanyaan secara langsung. Implementasi perlu menentukan mesin penalaran dan penyimpanan bukti baris. |
| Ontologi | Mendefinisikan arti `Function`, `Method`, dan hubungan pemanggilan. Jawaban tentang proyek nyata membutuhkan instans hasil ekstraksi serta mekanisme kueri. |
| **RDF dan SPARQL** | Triple menyimpan fakta yang dapat dilacak ke sumber. SPARQL mengikat variabel pemanggil dan menggabungkannya dengan lokasi bukti. Turtle mudah diperiksa dan dibawa bersama workspace. |
| Knowledge graph dengan Neo4j | Pencarian pola dengan Cypher juga langsung menyatakan sisi pemanggilan. Database dan browser graf cocok untuk eksplorasi bersama, dengan tambahan layanan yang harus tersedia saat demo. |

Pilihan utama tugas adalah **RDF/SPARQL** dengan skema ringan sebagai kosakata domain. Folder workspace dipilih agar agen terminal dan manusia dapat mengakses hasil yang sama tanpa membuka editor. Extension VS Code dapat ditambahkan sebagai klien untuk lompat ke definisi atau bukti panggilan.

### Hubungan dengan Graphify

Graphify memetakan kode dan materi seperti dokumentasi ke dalam graf persisten. Untuk kode, simpul dapat mewakili file, class, atau fungsi, dan relasi menghubungkan struktur maupun dependensi. Graphify juga mendokumentasikan sumber atau tingkat kepastian relasi serta menyediakan visualisasi dan penelusuran graf. CodeKG mengambil pola indeks lokal yang dapat dipakai ulang. Cakupan implementasi ini adalah fakta struktural Python, inventaris file, bukti baris, Turtle, SPARQL, dan HTML offline. Ekstraksi konsep dari prosa dan pengelompokan komunitas merupakan fitur referensi Graphify. [Repositori resmi Graphify](https://github.com/Graphify-Labs/graphify)

## Evaluasi yang dijalankan

Pengukuran dilakukan sekali per skenario pada Windows dengan Python 3.13, RDFLib 7.6, dan ripgrep 15.2. Dua salinan identik demo dipakai, satu untuk setiap alat. Waktu mencakup startup proses CLI. “File dibuka” menghitung file sumber unik yang dibaca secara eksplisit untuk verifikasi setelah pencarian. Jumlah itu berbeda dari banyaknya file yang dipindai alat.

**Biaya awal CodeKG** adalah satu build selama 0,782 detik untuk 6 file, 8 simbol, 3 lokasi teresolusi, 1 lokasi dinamis, dan 0 kesalahan parse. Angka berikut mengecualikan build dan waktu pembacaan manual.

| Pertanyaan | Alur | Perintah pencarian | File dibuka | Waktu pencarian | Hasil |
|---|---|---:|---:|---:|---|
| Di mana definisi `verify_token`? | `rg` dengan pola deklarasi | 1 | 0 | 0,029 dtk | `auth/tokens.py:4` |
| Sama | `codekg find` | 1 | 0 | 0,855 dtk | File dan baris yang sama |
| Siapa pemanggilnya dan di mana? | `rg` nama asli lalu alias | 2 | 1 | 0,047 dtk | Tiga baris, lingkup pemanggil dibaca di sumber |
| Sama | `codekg find` lalu `callers` | 2 | 1 | 1,620 dtk | Dua nama pemanggil dan tiga baris, diverifikasi di sumber |

Perintah pembanding berikut dijalankan dari root salinan demo:

```powershell
rg -n '^def verify_token\(' -g '*.py' .
rg -n -w verify_token -g '*.py' .
rg -n '\bcheck\(' app/service.py
Get-Content app/service.py
```

Pada demo kecil ini, `rg` lebih cepat untuk kedua pertanyaan. CodeKG memberikan identitas pemanggil, arah relasi, dan pemetaan alias langsung dalam JSON. Jika agen telah menyimpan ID dari putaran sebelumnya, pertanyaan lanjutan cukup memakai `callers`. Pengukuran ini belum menguji penghematan token ataupun waktu pada repositori besar.

## Pengujian dan batas analisis

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Suite memakai salinan sementara demo untuk memeriksa CLI, bukti SPARQL dan HTML, impor relatif dan alias, nama yang tertutup parameter lokal, aturan ignore, file gagal diparse, serta perubahan ID dan relasi sesudah rebuild. Viewer juga diuji dengan Edge headless dalam kondisi offline untuk membuka file, mencari simbol, memilih bukti, dan memfilter method.

Hasil adalah pendekatan statis atas sumber Python. Parameter callback, lookup melalui kamus, impor eksternal, serta dispatch method pada instance yang tipe konkretnya belum diketahui dapat berstatus `unresolved`. Implementasi mengambil pendekatan konservatif pada wildcard import, nama dengan beberapa binding, lambda, dan comprehension. Analisis belum memodelkan efek decorator, monkey patch, atau perubahan binding saat runtime. Bukti untuk relasi panggilan menyertakan lokasi ekspresi. Relasi struktural lain pada viewer memperlihatkan lokasi entitas sumber dan tujuan. CLI memuat ulang Turtle pada setiap proses, sehingga waktu kueri pada proyek besar perlu diukur tersendiri.
