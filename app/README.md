# Runway app — web, iOS, Android

One Expo (React Native) codebase ships to all three platforms. Routes live in `src/app/`
(Expo Router): `index.tsx` (Today), `ask.tsx` (Ask), `spending.tsx` (Spending).

## Run

```bash
npm install
npx expo start          # then press w (web), i (iOS simulator), a (Android emulator)
                        # or scan the QR code with Expo Go on your phone
```

The app talks to the backend at `EXPO_PUBLIC_API_URL` (default `http://localhost:8000`).
Start the backend first — see `backend/README.md`. On a physical phone, create `app/.env` with
`EXPO_PUBLIC_API_URL=http://<your-laptop-LAN-IP>:8000`.

## Rules

- Add packages with `npx expo install <pkg>` (never plain npm) — and `git pull` first.
- Read `AGENTS.md`: Expo APIs change every SDK, so check the versioned docs, not memory.
- Shared files (`src/lib/*`, navigation) change only via PR — see `docs/TEAM.md`.
- Known: `npx tsc --noEmit` reports 3 errors inside Expo's starter template files
  (CSS-module typings, a `Pressable` ref type). They don't affect the build; fix if you touch those files.
