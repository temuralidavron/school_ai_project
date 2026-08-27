# Maktab tarmog'i — NOLDAN, sodda tilda (charchagan miya uchun)

Har safar maktabga borganda shu faylni oching. Hech narsa yodlash shart
emas — tepadan pastga qarab yuring.

---

## 1. Maktab tarmog'i aslida nima (1 daqiqalik rasm)

```
[Internet] --- [MIKROTIK router] --- [Switch (taqsimlagich quti)]
                                        |--- kamera 1 (masalan 10.144.9.11)
                                        |--- kamera 2 (10.144.9.12)
                                        |--- ...
                                        |--- BIZNING SERVER shu yerga ulanadi
```

Oddiy qilib:
- **Mikrotik** — maktabning bosh routeri. Biz unga odatda TEGMAYMIZ.
- **Switch** — ko'p portli quti, kameralar simlari shunga kirgan.
- **IP manzil** — har qurilmaning "uy manzili", masalan `10.144.9.11`.
- **Tarmoq (subnet)** — "ko'cha": `10.144.9.x` degani — birinchi uch son
  bir xil, oxirgisi har qurilmada har xil. **Server kameralar bilan bitta
  ko'chada bo'lishi SHART** — aks holda ularni "ko'rmaydi".
- **554-port** — kameraning RTSP "eshigi": video shu eshikdan olinadi.

## 2. Borgach IT odamdan so'raladigan 3 SAVOL (yozib oling)

1. **"Kameralar qaysi IP oralig'ida?"** — javob masalan: `10.144.9.x`
   yoki `192.168.88.x`. Bilmasa: "Mikrotikda DHCP leases ro'yxatini
   ko'rsating" deng — kameralar ro'yxatda ko'rinadi.
2. **"Kamera login/paroli nima?"** — odatda `admin/admin` yoki
   `admin/<maktab paroli>`.
3. **"Serverni qaysi portga ulasam kameralarni ko'radi?"** — kameralar
   ulangan switch'ning bo'sh portini ko'rsatsin. (Agar "kameralar alohida
   VLANda" desa — "shu portni kamera VLANiga qo'shib bering" deng.
   Buni IT odam Mikrotik/switchda 1 daqiqada qiladi — o'zingiz Winbox'ga
   kirmang, bu ularning ishi.)

IT odam yo'q bo'lsa: kameralarning simi qayerga borayotganini ko'zingiz
bilan kuzating — o'sha qutining bo'sh portiga ulang.

## 3. Serverni ulash va IP olish (5 daqiqa)

Kabelni uladingiz. Server terminalida:

```bash
ip -4 a
```

O'qish: `inet 10.144.9.37/24 ... enp4s0` ko'rsangiz — interfeys nomi
`enp4s0` (yoki `eno1`), IP `10.144.9.37`. Ikki holat:

**A) IP o'zi keldi (DHCP bor)** — birinchi uch son kameralarniki bilan
bir xilmi? Bir xil bo'lsa — 4-bo'limga o'ting.

**B) IP kelmadi yoki boshqa ko'chada** — vaqtinchalik qo'lda beramiz.
Kameralar `10.144.9.x` bo'lsa (misol), bo'sh raqam sifatida 250 olamiz:

```bash
sudo ip addr add 10.144.9.250/24 dev enp4s0
```

(`enp4s0` o'rniga o'z interfeysingiz; `10.144.9` o'rniga IT aytgan ko'cha.)

**DIQQAT: bu vaqtinchalik — reboot'da o'chadi!** Hammasi ishlagach
DOIMIY qiling (netplan) — [RTSP_MAKTAB.md](RTSP_MAKTAB.md) 6b-bo'limda
tayyor shablon bor. Buni qilmasangiz tok o'chib-yonsa davomat jim to'xtaydi.

## 4. Kameralarni ko'ryapmizmi — zinapoya tekshiruv

Har pog'ona ishlamasa, o'sha pog'onadagi izohga qarang:

```bash
# 1-pog'ona: umuman bitta ko'chadamizmi?
ip a | grep 10.144
#   chiqmasa -> 3-bo'limga qayting (IP yo'q)

# 2-pog'ona: kamera javob beradimi?
ping -c 3 10.144.9.11
#   javob yo'q -> kabel/port noto'g'ri yoki VLAN ochilmagan -> IT odamga:
#   "shu portni kamera VLANiga qo'shing"

# 3-pog'ona: RTSP eshigi ochiqmi?
timeout 3 bash -c 'echo > /dev/tcp/10.144.9.11/554' && echo OCHIQ || echo YOPIQ
#   YOPIQ -> bu IP kamera emas (printer/boshqa narsa bo'lishi mumkin)
```

## 5. ASOSIY BUYRUQ — qolganini skript o'zi qiladi

IP oralig'ini bilsangiz (masalan `10.144.9.x`):

```bash
cd ~/school_ai_project
bash deploy/rtsp_tayyorla.sh --org-id <36 yoki 24> --scan 10.144.9
```

Bu skript: butun ko'chani aylanadi -> 554 ochiq qurilmalarni topadi ->
har birida 8 xil RTSP yo'lni HAQIQIY kadr o'qib sinaydi -> ishlaganlarini
ro'yxat qiladi. Login boshqa bo'lsa: `--user admin --pass PAROL` qo'shing.

Natijada "KADR OK ... /stream1" kabi qatorlar chiqadi — bular tirik
kameralar. Keyingi qadamlar (qaysi IP qaysi xona, CSV, ishga tushirish) —
[MAKTAB_49.md](MAKTAB_49.md) yoki [MAKTAB_207.md](MAKTAB_207.md) 3-bo'limda.

## 6. Tez-tez chiqadigan muammolar jadvali

| Ko'rinish | Sababi | Yechim |
|---|---|---|
| `ip a` da kamera ko'chasidan IP yo'q | DHCP yo'q yoki boshqa VLAN | 3-bo'lim B) qo'lda IP; yoki IT: "portni kamera VLANiga" |
| ping YO'Q | kabel/port/VLAN | boshqa portga ulab ko'ring; IT odam |
| ping OK, 554 YOPIQ | bu qurilma kamera emas | skanerdan chiqqan boshqa IP larni sinang |
| 554 ochiq, "kadr YO'Q" | login/parol boshqa | `--user/--pass` bilan qayta; kamera web sahifasi: brauzerda `http://<kamera_ip>` |
| MJPEG'da boshqa xona ko'rinyapti | IP-xona chalkash | MAKTAB_XX.md 3-qadam: bittalab ko'rib CSV to'g'rilang |
| Hammasi ishladi, ertasiga o'lik | vaqtinchalik IP reboot'da o'chgan | netplan (RTSP_MAKTAB 6b) — DOIMIY qiling |

## 7. Mikrotik haqida esda tutish

- Biz Mikrotik SOZLAMAYMIZ — faqat IT odamdan port/VLAN so'raymiz.
- Mikrotik'ka kirish kerak bo'lgan yagona holat: kamera IP larini bilish
  (DHCP leases ro'yxati) — buni ham IT odam ochib ko'rsatsin.
- PTZ (kamera burish) proxy orqali O'TMAYDI — faqat shu lokal tarmoqdan.

## 8. Bitta varaq — to'liq ketma-ketlik (nusxalab yurish uchun)

```bash
ip -4 a                                              # qayerdaman?
ping -c 3 <kamera_ip>                                # ko'ryapmanmi?
sudo ip addr add <ko'cha>.250/24 dev <interfeys>     # kerak bo'lsa IP
cd ~/school_ai_project
bash deploy/start.sh status                          # tizim tirikmi
bash deploy/rtsp_tayyorla.sh --org-id <N> --scan <ko'cha>   # kameralar
# ... xonalarni aniqlash + CSV (MAKTAB_XX.md 3-4 qadam)
docker compose exec web python3.14 manage.py add_cameras --org-id <N> --csv deploy/cameras_XX.csv --activate
docker compose exec web python3.14 manage.py sync_full --org-id <N>
bash deploy/rtsp_tayyorla.sh --org-id <N> --apply
bash deploy/start.sh rtsp --org-id <N> --skud izolyatsiya   # AVVAL SHU!
# hammasi to'g'ri bo'lgach:
bash deploy/start.sh rtsp --org-id <N> --skud real
# va DOIMIY IP (netplan) — RTSP_MAKTAB.md 6b!
```

Miya ishlamay qolsa: macOS'da Claude'ni oching — DAVOM.md orqali hammasini
biladi, shu faylni birga bosib o'tasiz.
