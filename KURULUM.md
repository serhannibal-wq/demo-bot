# Ücretsiz kurulum (GitHub, ~10 dakika)

Bot her 4 saatte GitHub'ın sunucularında kendiliğinden çalışır. Panel ise ücretsiz bir web adresinde yayınlanır. Bilgisayarının açık kalmasına gerek yok, kredi kartı gerekmez.

## 1. Depo oluştur
1. github.com'da ücretsiz hesap aç (varsa giriş yap).
2. Sağ üstte **+ → New repository**.
3. Ad: `demo-bot`, **Public** seç (ücretsiz panel için gerekli; içinde para ya da şifre yok, sadece demo sonuçlar var). **Create repository**.

## 2. Dosyaları yükle
1. Depo sayfasında **uploading an existing file** bağlantısına tıkla.
2. `binance_demo_bot.py` ve `index.html` dosyalarını sürükle. **Commit changes**.
3. Bot dosyası için: **Add file → Create new file**. Dosya adına tam olarak şunu yaz: `.github/workflows/bot.yml`
   Paketteki `bot.yml` dosyasının içeriğini kopyalayıp yapıştır. **Commit changes**.
   (Klasör sürüklerken `.github` gizli klasörü bazen atlanır, bu yüzden bu adım elle.)

## 3. Botu başlat
1. Üstte **Actions** sekmesi → çıkan uyarıda iş akışlarını etkinleştir.
2. Soldan **demo-bot** → sağda **Run workflow** → **Run workflow**.
3. 1 dakika içinde yeşil ✓ görmelisin. Depoda `demo_state.json`, `equity_history.json` oluşur.
   Kırmızı ✗ çıkarsa: **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**, sonra tekrar çalıştır.

## 4. Paneli yayınla
1. **Settings → Pages**.
2. Source: **Deploy from a branch**, Branch: **main**, klasör **/ (root)** → **Save**.
3. 1–2 dakika sonra adres orada görünür: `https://KULLANICI-ADIN.github.io/demo-bot/`
   Bu adresi telefonundan da açabilirsin.

## Bilmen gerekenler
- Bot her gün 00:07, 04:07, 08:07, 12:07, 16:07, 20:07'de (UTC; Türkiye saatiyle +3) çalışır. GitHub bazen birkaç dakika geciktirir.
- GitHub'ın sunucuları ABD'de. `api.binance.com` ABD'ye kapalı olduğu için bot otomatik olarak Binance'in herkese açık veri adresine (`data-api.binance.vision`) geçer.
- Stratejiyi değiştirmek için `binance_demo_bot.py` dosyasında **CONFIG** kısmını GitHub üzerinden düzenle (kalem ikonu).
- Sıfırdan başlamak için `demo_state.json`, `demo_trades.csv` ve `equity_history.json` dosyalarını sil.
- Bu bir deney aracı, yatırım tavsiyesi değil.
