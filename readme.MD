# Stok Takip Uygulaması

Bu proje, FIFO yöntemine göre çalışan ve çok kullanıcılı erişim sunan basit bir stok takip sistemidir. Flask ve SQLite kullanılarak geliştirilmiştir.

## Özellikler
- Şifre korumalı kullanıcı girişi
- Yönetici, yönetici (onay yetkili) ve normal kullanıcı rolleri
- FIFO (First In, First Out) yöntemiyle stok çıkışı maliyet hesaplama
- Stok girişlerinde tedarikçi, fatura ve depo bilgisi takibi
- Proje bazlı stok çıkışı
- Stok talepleri için hiyerarşik onay süreci ve talep durum takibi
- Sipariş (tedarik) yönetimi ve durum güncellemeleri
- Manuel stok düzeltmeleri ve hareket günlüğü
- Stok durumu, fiyat geçmişi ve hareket raporları
- Kullanıcı yönetimi ekranı ve kullanıcı aktivite logları
- Düşük stok seviyeleri için uyarılar

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

## Varsayılan Roller
- **Admin**: Kullanıcı yönetimi ve tüm stok işlemleri.
- **Yönetici**: Stok giriş/çıkış işlemleri, talep onayı ve sipariş yönetimi.
- **Kullanıcı**: Stok talebi oluşturma ve kendi taleplerini görüntüleme.

## Notlar
- FIFO düşümleri stok giriş kayıtlarının `remaining_quantity` alanı üzerinden otomatik yapılır.
- Manuel stok düzeltmesi negatif girildiğinde stoktan düşer, pozitif girildiğinde sıfır maliyetli giriş kaydı oluşturur.
- Kullanıcı aktiviteleri ve stok hareketleri rapor sayfalarından izlenebilir.
