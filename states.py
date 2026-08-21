from aiogram.fsm.state import StatesGroup, State

class FillData(StatesGroup):
    waiting_for_title = State()
    waiting_for_artists = State()
    waiting_for_music_authors = State()
    waiting_for_wav_link = State()
    confirm_overwrite = State()

class EditData(StatesGroup):
    waiting_for_choice = State()
    waiting_for_file = State()
    waiting_for_title = State()
    waiting_for_artists = State()
    waiting_for_music_authors = State()
    waiting_for_wav_link = State()

class RejectTrack(StatesGroup):
    waiting_for_comment = State()