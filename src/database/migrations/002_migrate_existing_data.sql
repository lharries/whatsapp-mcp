
INSERT OR IGNORE INTO users (
    id, 
    username, 
    email, 
    password_hash, 
    phone_number,
    created_at
) VALUES (
    1,
    'default_user',
    'default@whatsapp-mcp.local',
    '$2b$10$defaulthashforexistingdata', -- Placeholder hash
    NULL,
    CURRENT_TIMESTAMP
);

UPDATE chats 
SET user_id = 1 
WHERE user_id IS NULL;

UPDATE messages 
SET user_id = 1 
WHERE user_id IS NULL;
