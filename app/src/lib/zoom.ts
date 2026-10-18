/**
 * The desktop website is drawn enlarged (public/index.html sets CSS zoom on <body>). Window sizes and
 * pointer positions from the browser are in on-screen pixels, while layout is in the app's own pixels,
 * so anything that mixes the two divides by this. Always 1 on phones and in the native apps.
 */
import { Platform } from 'react-native';

export function zoom(): number {
  if (Platform.OS !== 'web' || typeof document === 'undefined') return 1;
  return parseFloat(document.body?.style.zoom) || 1;
}
