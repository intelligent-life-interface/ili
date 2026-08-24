/**
 * Update Banner — zeigt verfügbare ili-Updates an.
 *
 * Lädt beim Start GET /api/update-status und zeigt ein Banner, wenn ein
 * Update verfügbar ist. Banner kann geschlossen werden. Prüft alle 24h neu.
 *
 * Texte via i18n: "update.banner.*"
 */

async function initUpdateBanner() {
  const bannerId = 'update-banner-container';
  const existingBanner = document.getElementById(bannerId);

  if (existingBanner) {
    console.debug('[UpdateBanner] Container already exists');
    return;
  }

  try {
    console.debug('[UpdateBanner] Fetching /api/update-status');
    const response = await fetch('/api/update-status');
    if (!response.ok) {
      console.warn('[UpdateBanner] Failed to fetch update status:', response.status);
      return;
    }

    const status = await response.json();
    console.debug('[UpdateBanner] Status:', status);

    if (!status.update_available) {
      console.debug('[UpdateBanner] No update available');
      return;
    }

    const dismissedVersion = localStorage.getItem('update-banner-dismissed');
    if (dismissedVersion && dismissedVersion === status.available_version) {
      console.debug('[UpdateBanner] Dismissed for this version, not showing again:', dismissedVersion);
      return;
    }

    // Build banner HTML
    const container = document.createElement('div');
    container.id = bannerId;
    container.className = 'update-banner-wrapper';

    const banner = document.createElement('div');
    banner.className = 'update-banner';
    if (status.is_prerelease) {
      banner.classList.add('update-banner--beta');
    }

    // Title: ili X verfügbar (installiert Y)
    const currentVersion = status.current_version || 'unknown';
    const availableVersion = status.available_version || 'unknown';
    const title = document.createElement('div');
    title.className = 'update-banner__title';

    const titleText = window.t
      ? window.t('update.banner.title', 'ili {available} verfügbar')
      : 'ili ' + availableVersion + ' verfügbar';

    title.innerHTML = titleText.replace('{available}', availableVersion);

    const subtitle = document.createElement('div');
    subtitle.className = 'update-banner__subtitle';
    const subtitleText = window.t
      ? window.t('update.banner.installed', 'installiert: {version}')
      : 'installiert: ' + currentVersion;
    subtitle.innerHTML = subtitleText.replace('{version}', currentVersion);

    // Metadata
    const meta = document.createElement('div');
    meta.className = 'update-banner__meta';

    // Beta label if prerelease
    if (status.is_prerelease) {
      const betaLabel = document.createElement('span');
      betaLabel.className = 'update-banner__badge';
      betaLabel.innerHTML = window.t
        ? window.t('update.banner.beta', '🧪 Beta')
        : '🧪 Beta';
      meta.appendChild(betaLabel);
    }

    // Release link
    if (status.available_url) {
      const link = document.createElement('a');
      link.href = status.available_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.className = 'update-banner__link';
      link.innerHTML = window.t
        ? window.t('update.banner.changes', '→ Änderungen')
        : '→ Änderungen';
      meta.appendChild(link);
    }

    // Instructions: copy ili-update.sh
    const instructions = document.createElement('div');
    instructions.className = 'update-banner__instructions';

    const instructionsLabel = document.createElement('div');
    instructionsLabel.className = 'update-banner__instructions-label';
    instructionsLabel.innerHTML = window.t
      ? window.t('update.banner.howto', 'Zum Aktualisieren:')
      : 'Zum Aktualisieren:';

    const copyTitle = window.t
      ? window.t('update.banner.copy_title', 'In Zwischenablage kopieren')
      : 'In Zwischenablage kopieren';
    const copyAria = window.t
      ? window.t('update.banner.copy_aria', 'Kopieren')
      : 'Kopieren';

    const instructionsCode = document.createElement('div');
    instructionsCode.className = 'update-banner__instructions-code';
    instructionsCode.innerHTML =
      '<code>./ili-update.sh</code>' +
      '<button class="update-banner__copy-btn" title="' + copyTitle + '" aria-label="' + copyAria + '">📋</button>';

    instructions.appendChild(instructionsLabel);
    instructions.appendChild(instructionsCode);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'update-banner__close';
    closeBtn.innerHTML = '✕';
    closeBtn.setAttribute('aria-label', window.t
      ? window.t('update.banner.close', 'Schliessen')
      : 'Schliessen');

    closeBtn.addEventListener('click', () => {
      container.remove();
      localStorage.setItem(
        'update-banner-dismissed',
        availableVersion
      );
      console.debug('[UpdateBanner] Dismissed for version', availableVersion);
    });

    // Copy button handler
    const copyBtn = instructionsCode.querySelector('.update-banner__copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText('./ili-update.sh').then(() => {
          const original = copyBtn.innerHTML;
          copyBtn.innerHTML = '✓';
          setTimeout(() => {
            copyBtn.innerHTML = original;
          }, 2000);
          console.debug('[UpdateBanner] Copied to clipboard');
        }).catch(err => {
          console.error('[UpdateBanner] Copy failed:', err);
        });
      });
    }

    // Assemble
    banner.appendChild(title);
    banner.appendChild(subtitle);
    banner.appendChild(meta);
    banner.appendChild(instructions);
    banner.appendChild(closeBtn);

    container.appendChild(banner);

    // Insert after error-banner if it exists, otherwise as first child of header
    const errorBanner = document.querySelector('.error-banner');
    const header = document.querySelector('header.ds-zone-top');

    if (header) {
      if (errorBanner) {
        errorBanner.parentNode.insertBefore(container, errorBanner.nextSibling);
      } else {
        header.insertBefore(container, header.firstChild);
      }
      console.debug('[UpdateBanner] Banner inserted');
    }
  } catch (err) {
    console.error('[UpdateBanner] Init failed:', err);
  }
}

// Auto-init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initUpdateBanner);
} else {
  initUpdateBanner();
}
