const express = require('express');
const bcrypt = require('bcryptjs');
const db = require('../db');
const asyncHandler = require('../utils/asyncHandler');
const validateBody = require('../middleware/validate');
const { userCreateSchema, passwordChangeSchema } = require('../validators');
const { requireAuth } = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

router.get('/', (_, res) => {
  const rows = db.prepare('SELECT id, username, created_at, last_login FROM admin_users ORDER BY id').all();
  res.json(rows);
});

router.post(
  '/',
  validateBody(userCreateSchema),
  asyncHandler(async (req, res) => {
    const { username, password } = req.body;
    const exists = db.prepare('SELECT id FROM admin_users WHERE username = ?').get(username);
    if (exists) return res.status(409).json({ error: 'Username déjà utilisé' });

    const hash = await bcrypt.hash(password, 12);
    const info = db.prepare('INSERT INTO admin_users (username, password_hash) VALUES (?, ?)').run(username, hash);
    const row = db.prepare('SELECT id, username, created_at, last_login FROM admin_users WHERE id = ?').get(Number(info.lastInsertRowid));
    res.status(201).json(row);
  })
);

router.delete('/:id', (req, res) => {
  const count = db.prepare('SELECT COUNT(*) AS c FROM admin_users').get().c;
  if (count <= 1) return res.status(409).json({ error: 'Impossible de supprimer le dernier admin' });
  const info = db.prepare('DELETE FROM admin_users WHERE id = ?').run(req.params.id);
  if (!info.changes) return res.status(404).json({ error: 'Utilisateur introuvable' });
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(req.params.id);
  res.json({ ok: true });
});

router.put(
  '/:id/password',
  validateBody(passwordChangeSchema),
  asyncHandler(async (req, res) => {
    const { current_password, new_password } = req.body;
    const user = db.prepare('SELECT id, password_hash FROM admin_users WHERE id = ?').get(req.params.id);
    if (!user) return res.status(404).json({ error: 'Utilisateur introuvable' });
    if (req.user.id !== user.id) return res.status(403).json({ error: 'Action interdite' });

    const ok = await bcrypt.compare(current_password, user.password_hash);
    if (!ok) return res.status(401).json({ error: 'Mot de passe actuel incorrect' });

    const hash = await bcrypt.hash(new_password, 12);
    db.prepare('UPDATE admin_users SET password_hash = ? WHERE id = ?').run(hash, user.id);
    res.json({ ok: true });
  })
);

module.exports = router;
