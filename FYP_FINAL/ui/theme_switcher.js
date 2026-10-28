/** Native appearance adapter for Streamlit 1.66.x.
 * Selects the existing appearance control so Streamlit updates its own theme,
 * canvases, overlays and persisted preference. Never touches app widget values.
 * Uses only trusted static component markup and accessible native UI controls.
 */
export default function({ parentElement }) {
    const button = parentElement.querySelector('#oa-theme-toggle');
    const label = parentElement.querySelector('.theme-label');
    const app = document.querySelector('[data-testid="stApp"]');
    if (!button || !app) return;
    if (!button || !app) return;
    let busy = false;
    let initialized = false;
    const storageKey = "office-appearance-v1";
    const mode = () => getComputedStyle(app).colorScheme.includes('light') ? 'light' : 'dark';
    const sync = () => {
        const light = mode() === 'light';
        document.documentElement.style.colorScheme = light ? 'light' : 'dark';
        button.setAttribute('aria-checked', String(light));
        button.setAttribute('aria-label', light ? 'Switch to Dark mode' : 'Switch to Light mode');
        button.title = light ? 'Light mode · switch to Dark mode' : 'Dark mode · switch to Light mode';
        label.textContent = light ? 'Light' : 'Dark';
        if (initialized) { document.documentElement.dataset.oaAppearanceMode = light ? 'light' : 'dark'; try { localStorage.setItem(storageKey, light ? 'light' : 'dark'); } catch (_) { /* private browsing */ } }
    };
    const find = async (selector) => {
        for (let i = 0; i < 40; i++) {
            const element = document.querySelector(selector);
            if (element) return element;
            await new Promise(resolve => setTimeout(resolve, 25));
        }
        return null;
    };
    const select = async (requested) => {
        if (busy) return;
        busy = true;
        const desired = requested || (mode() === 'dark' ? 'Light' : 'Dark');
        const menuButton = document.querySelector('[data-testid="stMainMenuButton"]');
        // If the native menu is unavailable, preserve the working current theme.
        if (!menuButton) { busy = false; return; }
        document.documentElement.classList.add('oa-selecting-theme');
        try {
            const selector = `[data-testid="stMainMenuItem-theme-${desired}"]`;
            if (!document.querySelector(selector)) menuButton.click();
            const option = await find(selector);
            if (!option) {
                // Leave the normal native appearance menu available as a fallback.
                button.title = 'Choose Light or Dark in the appearance menu';
                return;
            }
            option.click();
            if (document.querySelector('[role="menu"]')) menuButton.click();
            await new Promise(resolve => requestAnimationFrame(resolve));
            sync();
        } finally {
            document.documentElement.classList.remove('oa-selecting-theme');
            busy = false;
            button.focus({ preventScroll:true });
        }
    };
    const onClick = () => select();
    button.addEventListener('click', onClick);
    const observer = new MutationObserver(sync);
    observer.observe(app, { attributes:true, attributeFilter:['class','style'] });
    const initialize = async () => {
        let saved = document.documentElement.dataset.oaAppearanceMode || 'dark';
        try { if (localStorage.getItem(storageKey) === 'light') saved = 'light'; } catch (_) { /* default dark */ }
        try {
            if (mode() !== saved) await select(saved === 'light' ? 'Light' : 'Dark');
        } finally {
            initialized = true;
            sync();
            document.documentElement.dataset.oaAppearanceReady = 'true';
        }
    };
    initialize();
    return () => { observer.disconnect(); button.removeEventListener('click', onClick); };
}
