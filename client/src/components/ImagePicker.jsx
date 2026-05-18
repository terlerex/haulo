import { useRef, useState, useCallback } from 'react';
import { api } from '../api.js';

const MAX_SIZE = 5 * 1024 * 1024;
const ALLOWED_EXT = ['.jpg', '.jpeg', '.png', '.webp'];
const ALLOWED_MIME = ['image/jpeg', 'image/png', 'image/webp'];

function validateFile(file) {
  if (!file) return 'Aucun fichier';
  if (file.size > MAX_SIZE) return 'Fichier > 5 MB';
  const name = (file.name || '').toLowerCase();
  const okExt = ALLOWED_EXT.some((e) => name.endsWith(e));
  const okMime = ALLOWED_MIME.includes(file.type);
  if (!okExt || !okMime) return 'Format non autorisé (jpg, jpeg, png, webp)';
  return null;
}

function uploadWithProgress(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch (e) { reject(e); }
      } else {
        let msg = `HTTP ${xhr.status}`;
        try { const j = JSON.parse(xhr.responseText); if (j.error) msg = j.error; } catch (_) {}
        reject(new Error(msg));
      }
    };
    xhr.onerror = () => reject(new Error('Erreur réseau'));
    const fd = new FormData();
    fd.append('file', file);
    xhr.send(fd);
  });
}

export default function ImagePicker({ value, onChange }) {
  const initialMode = value && value.startsWith('/uploads/') ? 'upload' : 'url';
  const [mode, setMode] = useState(initialMode);
  const [error, setError] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [imgBroken, setImgBroken] = useState(false);
  const fileInputRef = useRef(null);

  const set = (url) => {
    setImgBroken(false);
    onChange(url);
  };

  const handleFile = useCallback(async (file) => {
    setError(null);
    const err = validateFile(file);
    if (err) { setError(err); return; }
    setUploading(true);
    setProgress(0);
    try {
      // si une image uploadée précédemment existe, la supprimer
      if (value && value.startsWith('/uploads/')) {
        const filename = value.split('/').pop();
        try { await api.deleteUpload(filename); } catch (_) {}
      }
      const { url } = await uploadWithProgress(file, setProgress);
      set(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }, [value]);

  const onDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onPick = (e) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = '';
  };

  const clearImage = async () => {
    if (value && value.startsWith('/uploads/')) {
      const filename = value.split('/').pop();
      try { await api.deleteUpload(filename); } catch (_) {}
    }
    set('');
  };

  const isUploaded = value && value.startsWith('/uploads/');

  return (
    <div>
      <div className="flex gap-1 mb-2">
        <button
          type="button"
          onClick={() => setMode('url')}
          className={`px-3 py-1.5 rounded-md text-sm ${mode === 'url' ? 'bg-zinc-800 text-white' : 'bg-zinc-900 text-sub hover:text-white'}`}
        >
          🔗 Via URL
        </button>
        <button
          type="button"
          onClick={() => setMode('upload')}
          className={`px-3 py-1.5 rounded-md text-sm ${mode === 'upload' ? 'bg-zinc-800 text-white' : 'bg-zinc-900 text-sub hover:text-white'}`}
        >
          📁 Depuis mon ordinateur
        </button>
      </div>

      {mode === 'url' ? (
        <div className="space-y-2">
          <input
            type="url"
            value={value || ''}
            onChange={(e) => set(e.target.value)}
            placeholder="https://…"
            className="w-full bg-ink border border-zinc-800 rounded-md px-3 py-2 text-sm"
          />
          {value && (
            <button type="button" onClick={() => set('')} className="text-xs text-sub hover:text-white">
              Effacer
            </button>
          )}
        </div>
      ) : (
        <div>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className="rounded-lg border-2 border-dashed border-zinc-700 hover:border-zinc-500 bg-zinc-950/50 p-6 text-center transition-colors"
          >
            <div className="text-4xl mb-2">📤</div>
            <p className="text-sm text-sub mb-3">Glisse ton image ici (jpg, png, webp, 5 MB max)</p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 rounded-md bg-zinc-800 hover:bg-zinc-700 text-sm"
            >
              Parcourir
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              onChange={onPick}
              className="hidden"
            />
          </div>

          {uploading && (
            <div className="mt-3">
              <div className="text-xs text-sub mb-1">Upload {progress}%</div>
              <div className="h-2 bg-zinc-800 rounded overflow-hidden">
                <div className="h-full bg-emerald-500 transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          )}

          {isUploaded && !uploading && (
            <button
              type="button"
              onClick={clearImage}
              className="mt-3 text-xs px-3 py-1.5 rounded-md bg-red-900/40 hover:bg-red-800/60 text-red-200"
            >
              Supprimer l'image
            </button>
          )}
        </div>
      )}

      {error && (
        <div className="mt-2 text-sm text-red-400 bg-red-950/40 border border-red-900/50 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {/* Aperçu commun */}
      {value && !uploading && (
        <div className="mt-3">
          <div className="text-xs uppercase tracking-wider text-sub mb-1">Aperçu</div>
          <div className="aspect-video max-w-xs rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 flex items-center justify-center">
            {imgBroken ? (
              <div className="text-sub text-sm">Image non chargée</div>
            ) : (
              <img
                src={value}
                alt=""
                className="w-full h-full object-cover"
                onError={() => setImgBroken(true)}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
