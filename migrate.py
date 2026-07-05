import os
import time
import sys
from yandex_music import Client
from yandex_music.exceptions import YandexMusicError

# Считываем токены из переменных окружения (идеально для Docker)
SOURCE_TOKEN = os.environ.get('SOURCE_TOKEN')
TARGET_TOKEN = os.environ.get('TARGET_TOKEN')

def get_playlist_revision(client, kind):
    """Получает актуальную ревизию плейлиста для предотвращения конфликтов API."""
    try:
        pl_data = client.users_playlists(kind)
        if isinstance(pl_data, list) and len(pl_data) > 0:
            return pl_data[0].revision
        return pl_data.revision
    except Exception as e:
        print(f"Ошибка при получении ревизии для плейлиста {kind}: {e}")
        return None

def migrate_likes(client_source, client_target):
    print("\n=== Шаг 1: Перенос треков 'Мне нравится' ===")
    try:
        likes_tracks = client_source.users_likes_tracks()
        if not likes_tracks:
            print("В исходном аккаунте нет лайкнутых треков.")
            return
        
        track_ids = [track.track_id for track in likes_tracks]
        track_ids.reverse()  # Переворачиваем, чтобы сохранить хронологию
        total_tracks = len(track_ids)
        print(f"Найдено лайкнутых треков: {total_tracks}")
        
        batch_size = 50
        success_count = 0
        for i in range(0, total_tracks, batch_size):
            batch = track_ids[i:i + batch_size]
            try:
                client_target.users_likes_tracks_add(batch)
                success_count += len(batch)
                print(f"Прогресс лайков: {success_count}/{total_tracks} треков перенесено.")
            except YandexMusicError as e:
                print(f"Ошибка при переносе пакета лайков: {e}")
            time.sleep(1.5)
    except Exception as e:
        print(f"Не удалось перенести лайки: {e}")

def migrate_playlists(client_source, client_target):
    print("\n=== Шаг 2: Перенос пользовательских плейлистов ===")
    try:
        playlists = client_source.users_playlists_list()
    except Exception as e:
        print(f"Ошибка получения списка плейлистов: {e}")
        return

    if not playlists:
        print("Пользовательские плейлисты на исходном аккаунте не найдены.")
        return

    print(f"Найдено плейлистов для переноса: {len(playlists)}")
    
    for pl in playlists:
        print(f"\nОбработка плейлиста: '{pl.title}' (ID: {pl.kind})")
        
        # Получаем полную информацию о плейлисте (включая треки)
        try:
            full_pl = client_source.users_playlists(pl.kind)
            if isinstance(full_pl, list):
                full_pl = full_pl[0]
        except Exception as e:
            print(f"Не удалось получить детали плейлиста '{pl.title}': {e}")
            continue

        tracks = full_pl.tracks or []
        if not tracks:
            print(f"Плейлист '{pl.title}' пуст. Пропускаем.")
            continue

        print(f"Количество треков в плейлисте: {len(tracks)}")

        # Создаем аналогичный плейлист на целевом аккаунте
        try:
            visibility = getattr(pl, 'visibility', 'public')
            new_pl = client_target.users_playlists_create(title=pl.title, visibility=visibility)
            print(f"Создан новый плейлист '{pl.title}' (Новый ID/Kind: {new_pl.kind})")
        except Exception as e:
            print(f"Ошибка создания плейлиста '{pl.title}' на целевом аккаунте: {e}")
            continue

        # Поочередно добавляем треки
        success_tracks = 0
        current_revision = new_pl.revision
        
        for track_short in tracks:
            try:
                # Если ревизия сбросилась из-за прошлой ошибки, запрашиваем актуальную
                if current_revision is None:
                    current_revision = get_playlist_revision(client_target, new_pl.kind)

                result = client_target.users_playlists_insert_track(
                    playlist_id=new_pl.kind,
                    track_id=track_short.track_id,
                    album_id=track_short.album_id,
                    revision=current_revision
                )
                
                # Обновляем ревизию из ответа для следующего трека
                if isinstance(result, list) and len(result) > 0:
                    current_revision = result[0].revision
                elif hasattr(result, 'revision'):
                    current_revision = result.revision
                else:
                    current_revision = None
                
                success_tracks += 1
            except YandexMusicError as e:
                print(f"  [Ошибка] Не удалось добавить трек ID {track_short.track_id}: {e}")
                current_revision = None  # Сбрасываем ревизию для обновления на следующей итерации
            
            time.sleep(0.4)  # Пауза, чтобы Яндекс не заблокировал за спам-запросы
        
        print(f"Результат: успешно перенесено {success_tracks} из {len(tracks)} треков в плейлист '{pl.title}'.")
        time.sleep(2.0)

def main():
    if not SOURCE_TOKEN or not TARGET_TOKEN:
        print("Критическая ошибка: Переменные окружения SOURCE_TOKEN и TARGET_TOKEN обязательны.")
        sys.exit(1)

    print("Авторизация в сервисах Яндекс.Музыки...")
    try:
        client_source = Client(SOURCE_TOKEN).init()
        client_target = Client(TARGET_TOKEN).init()
        print("Авторизация выполнена успешно для обоих аккаунтов.")
    except YandexMusicError as e:
        print(f"Ошибка авторизации: {e}")
        sys.exit(1)

    # Запуск миграции
    migrate_likes(client_source, client_target)
    migrate_playlists(client_source, client_target)
    
    print("\n[Готово] Процесс миграции музыки полностью завершен!")

if __name__ == "__main__":
    main()