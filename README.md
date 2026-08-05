# Моніторинг територій бойових дій і тимчасово окупованих територій

Проєкт автоматично отримує актуальну редакцію офіційного переліку з `zakon.rada.gov.ua`, розбирає DOCX, перевіряє якість даних, зберігає кожну редакцію в PostgreSQL/Supabase та відображає поточні дані у Streamlit.

## Що виправлено порівняно зі старою версією

- попередня редакція більше не видаляється;
- порожній або підозріло малий результат не записується в базу;
- запис документа, рядків і змін виконується однією транзакцією;
- однаковий DOCX не завантажується повторно;
- зберігаються додані, вилучені та змінені записи;
- категорія визначається за заголовком секції з резервною перевіркою номера таблиці;
- номер базового наказу відокремлено від дати актуальної редакції;
- додано SQL-схему, тести та обробку помилок підключення.

## Структура

```text
.github/workflows/update-territories.yml  автоматичне щоденне оновлення
.github/workflows/tests.yml               перевірка коду після змін
.streamlit/config.toml                    оформлення Streamlit
.streamlit/secrets.toml.example           приклад локального секрету
data/oblast_centers.csv                   координати центрів областей
sql/schema.sql                            таблиці, індекси та views
src/config.py                             сталі параметри проєкту
src/document_source.py                    пошук і завантаження DOCX
src/parser.py                             розбір документа
src/validation.py                         захист від некоректних даних
src/database.py                           транзакційний запис та зміни
src/territory_service.py                  читання даних для застосунку
tests/                                    автоматичні тести
app.py                                    Streamlit-застосунок
run_parser.py                             оновлення даних
init_database.py                          створення схеми бази
```

## Порядок першого запуску

### 1. Завантаження на GitHub

Створіть порожній репозиторій `territories-monitor`. Відкрийте **Add file → Upload files** і перетягніть у вікно весь вміст цієї папки, включно з `.github`, `.streamlit`, `src`, `sql`, `data` та `tests`. Натисніть **Commit changes**.

Не завантажуйте ZIP одним файлом: спочатку розпакуйте його, а потім завантажте вміст.

### 2. Створення бази

Створіть PostgreSQL або Supabase-проєкт. У SQL Editor виконайте повний вміст `sql/schema.sql`.

Альтернативно локально:

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
python init_database.py
```

### 3. Секрет GitHub

У репозиторії відкрийте:

```text
Settings → Secrets and variables → Actions → New repository secret
```

Назва:

```text
DATABASE_URL
```

Значення — connection string PostgreSQL. Для хмарної бази має бути ввімкнене SSL; для Supabase доцільно використовувати Session pooler, доступний з GitHub Actions.

### 4. Перше завантаження даних

Відкрийте:

```text
Actions → Update territories → Run workflow
```

Після успішного виконання в таблиці `documents` з’явиться перша редакція, а `current_territory_status` покаже актуальний знімок.

### 5. Streamlit

Підключення до Streamlit виконується окремим етапом. Головний файл застосунку — `app.py`. У секретах Streamlit потрібно буде додати той самий `DATABASE_URL`.

## Локальна перевірка без бази

```bash
pip install -r requirements.txt
python run_parser.py --dry-run
```

Результат буде записано до `artifacts/territories_preview.csv`.

Для перевірки локального DOCX:

```bash
python run_parser.py --file path/to/list.docx --edition-date 2026-06-24 --dry-run
```

## Безпека оновлення

За замовчуванням оновлення припиниться, якщо новий знімок містить менше 65% записів попередньої редакції. Після ручної перевірки обмеження можна одноразово вимкнути через параметр `allow_large_drop` під час ручного запуску workflow.
