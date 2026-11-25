"""Emojis do seletor do compositor e das reações (a reação só aceita os desta lista)."""

REACOES_RAPIDAS = ('👍', '❤️', '😂', '😮', '🙏', '✅')

GRUPOS = (
    ('Rostos', ('😀', '😃', '😄', '😁', '😅', '😂', '🙂', '😉', '😊', '😍', '🥰', '😘', '😎', '🤩',
                '🤔', '😐', '😶', '🙄', '😬', '😮', '😢', '😭', '😡', '😴', '🤗', '🤝')),
    ('Gestos', ('👍', '👎', '👏', '🙌', '🙏', '👋', '👌', '✌️', '🤞', '💪', '👉', '☝️')),
    ('Símbolos', ('❤️', '💙', '💚', '💛', '🔥', '⭐', '✨', '🎉', '✅', '❌', '⚠️', '❗', '❓', '💯',
                  '📌', '⏰')),
    ('Objetos', ('📱', '💰', '💵', '💳', '🧾', '📄', '📎', '📅', '🏪', '🔒', '🔓', '📞')),
)

TODOS = tuple(dict.fromkeys(REACOES_RAPIDAS + tuple(e for _, grupo in GRUPOS for e in grupo)))
