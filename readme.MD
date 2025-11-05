# Stok Takip Uygulaması

Bu proje, FIFO yöntemine göre çalışan ve çok kullanıcılı erişim sunan basit bir stok takip sistemidir. Flask ve SQLite kullanılarak geliştirilmiştir.

## Özellikler
- Şifre korumalı kullanıcı girişi
- Yönetici, satınalma yöneticisi ve normal kullanıcı rolleri
- FIFO (First In, First Out) yöntemiyle stok çıkışı maliyet hesaplama
- Stok girişlerinde tedarikçi, fatura ve depo bilgisi takibi
- Proje bazlı stok çıkışı
- Proje yönetim ekranı ile proje ekleme ve güncelleme
- Stok talepleri için iki aşamalı (Satınalma Yöneticisi ➜ Proje Yöneticisi) onay süreci, termin tarihi planlama ve otomatik sipariş numarası üretimi
- Aynı talep içinde birden fazla ürün satırı ve satır bazlı proje seçimi
- Manuel stok düzeltmeleri ve hareket günlüğü
- Stok durumu, fiyat geçmişi ve hareket raporları
- Stok hareketlerini Excel formatında dışa aktarma
- Ayarlar paneli üzerinden stok düzeltme, proje, depo ve hareket geçmişi yönetimi
- Talep takip ekranı ile sipariş numarası bazında durum izleme ve PDF çıktısı
- Kullanıcı yönetimi ekranı, e-posta takibi ve kullanıcı aktivite logları
- Düşük stok seviyeleri için uyarılar
- Ürün kartlarında ürün kodu/detay güncelleme ve fotoğraf yükleme (yalnızca admin)
- Ürün kartlarında zorunlu birim seçimi ve Ayarlar > Birimler ekranı üzerinden birim yönetimi
- Ürün kategorileri, depo yönetimi ve kategori yönetim ekranı
- Çok satırlı stok giriş/çıkış formları ile tek seferde birden çok ürünü işlemeye ek olarak girişlerde anlık toplam maliyet hesaplaması
- Adminler için Ayarlar > E-posta Ayarları ekranı üzerinden SMTP bilgilerini yönetme ve E-posta Logları ile bildirim geçmişini izleme

## Kurulum
0. Proje klasörüne geçin:
   ```bash
   cd stoktakip
   ```
   > Windows'ta Komut İstemi kullanıyorsanız, `requirements.txt` dosyasının bulunduğu klasöre geçmeden sonraki adımlara devam ederseniz "No such file or directory" hatası alırsınız.
1. (İsteğe bağlı) Sanal ortam oluşturun ve etkinleştirin:
   - **Windows (Komut İstemi / PowerShell)**
     ```powershell
     python -m venv venv
     venv\Scripts\activate
     ```
   - **macOS / Linux**
     ```bash
     python -m venv venv
     source venv/bin/activate
     ```
   Sanal ortam kullanmak istemiyorsanız bu adımı atlayabilir ve sonraki adıma geçebilirsiniz.
2. Gerekli paketleri yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
3. Veritabanını oluşturun ve varsayılan kayıtları hazırlayın:
   ```bash
   flask --app app.py init-db
   ```
   İlk admin kullanıcısı `admin` kullanıcı adı ve `admin123` şifresi ile oluşturulur.
4. Gerekirse yeni bir yönetici hesabı oluşturun veya mevcut hesabın şifresini güncelleyin:
   ```bash
   flask --app app.py create-admin --username yeniadmin
   ```
   Komut şifreyi sizden gizli olarak isteyecek ve ilgili kullanıcıyı admin yetkisiyle oluşturacaktır (veya güncelleyecektir).
5. Uygulamayı çalıştırın:
   ```bash
   flask --app app.py run --debug
   ```

### E-posta Bildirimlerini Etkinleştirme (Opsiyonel)
Yeni stok talepleri oluşturulduğunda onaylayıcılara otomatik e-posta gönderimi için Ayarlar > E-posta Ayarları ekranından SMTP bilgilerini girebilir veya aşağıdaki ortam değişkenlerini tanımlayabilirsiniz:

| Değişken          | Açıklama                                   | Varsayılan |
| ----------------- | ------------------------------------------ | ---------- |
| `SMTP_SERVER`     | SMTP sunucu adresi                         | (gerekli)  |
| `SMTP_PORT`       | SMTP portu                                 | `587`      |
| `SMTP_USERNAME`   | SMTP kullanıcı adı                         | boş        |
| `SMTP_PASSWORD`   | SMTP şifresi                               | boş        |
| `SMTP_USE_TLS`    | TLS kullanılacak mı? (`true/false`)        | `true`     |
| `MAIL_SENDER`     | Gönderen e-posta adresi                    | `SMTP_USERNAME` |
| `SMTP_TIMEOUT`    | Sunucu yanıtı için bekleme süresi (saniye) | `10`       |

Ayarları arayüz üzerinden güncellediğinizde değerler veritabanına kaydedilir ve gönderim sonuçlarını Ayarlar > E-posta Logları ekranından takip edebilirsiniz.

Örnek kullanım (Linux/macOS):

```bash
export SMTP_SERVER=smtp.example.com
export SMTP_USERNAME=stokbot@example.com
export SMTP_PASSWORD=parola
export MAIL_SENDER=stokbot@example.com
```

Windows PowerShell için:

```powershell
$env:SMTP_SERVER = "smtp.example.com"
$env:SMTP_USERNAME = "stokbot@example.com"
$env:SMTP_PASSWORD = "parola"
$env:MAIL_SENDER = "stokbot@example.com"
```

Bu ayarlar tanımlandığında, talebi onaylayacak kişilere talep detaylarını ve ilgili bağlantıyı içeren e-postalar otomatik olarak iletilir.

## Varsayılan Roller
- **Admin**: Kullanıcı yönetimi ve tüm stok işlemleri.
- **Satınalma Yöneticisi**: Admin ile aynı yetkiler.
- **Yönetici**: Stok giriş/çıkış işlemleri, talep onayı ve sipariş yönetimi.
- **Kullanıcı**: Stok talebi oluşturma ve kendi taleplerini görüntüleme.

## Notlar
- FIFO düşümleri stok giriş kayıtlarının `remaining_quantity` alanı üzerinden otomatik yapılır.
- Manuel stok düzeltmesi negatif girildiğinde stoktan düşer, pozitif girildiğinde sıfır maliyetli giriş kaydı oluşturur.
- Kullanıcı aktiviteleri ve stok hareketleri ayarlar panelindeki bağlantılardan izlenebilir.
