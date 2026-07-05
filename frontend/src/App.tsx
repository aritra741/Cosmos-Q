import { AppDemo } from './AppDemo';
import { AppLive } from './AppLive';

/** Live backend by default; set VITE_DEMO_MODE=true for the scripted demo. */
export function App() {
  if (import.meta.env.VITE_DEMO_MODE === 'true') {
    return <AppDemo />;
  }
  return <AppLive />;
}
