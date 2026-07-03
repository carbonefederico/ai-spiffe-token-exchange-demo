const config = window.TELCO_CONFIG;
const tokenStorageKey = 'spiffe_demo_access_token';
const verifierStorageKey = 'spiffe_demo_pkce_verifier';
const stateStorageKey = 'spiffe_demo_oauth_state';

const els = {
  landingView: document.querySelector('#landingView'),
  homeView: document.querySelector('#homeView'),
  loginButton: document.querySelector('#loginButton'),
  heroLoginButton: document.querySelector('.hero-login-button'),
  devLoginButton: document.querySelector('#devLoginButton'),
  logoutButton: document.querySelector('#logoutButton'),
  openChatButton: document.querySelector('#openChatButton'),
  closeChatButton: document.querySelector('#closeChatButton'),
  firstNameGreeting: document.querySelector('#firstNameGreeting'),
  usernameDisplay: document.querySelector('#usernameDisplay'),
  chatDrawer: document.querySelector('#chatDrawer'),
  chatMessages: document.querySelector('#chatMessages'),
  chatForm: document.querySelector('#chatForm'),
  chatInput: document.querySelector('#chatInput'),
  tabButtons: document.querySelectorAll('.account-tab'),
  overviewPanel: document.querySelector('#overviewPanel'),
  tokenFlowPanel: document.querySelector('#tokenFlowPanel'),
  tokenHistory: document.querySelector('#tokenHistory'),
  refreshTokenHistoryButton: document.querySelector('#refreshTokenHistoryButton'),
  claimsModal: document.querySelector('#claimsModal'),
  claimsModalTitle: document.querySelector('#claimsModalTitle'),
  claimsModalBody: document.querySelector('#claimsModalBody'),
  closeClaimsModalButton: document.querySelector('#closeClaimsModalButton')
};

let openTokenJourneyStep = 0;

function base64Url(buffer) {
  return btoa(String.fromCharCode(...new Uint8Array(buffer)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

function randomString(length = 64) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

async function sha256(text) {
  return crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
}

function accessToken() {
  return sessionStorage.getItem(tokenStorageKey);
}

function setAccessToken(token) {
  sessionStorage.setItem(tokenStorageKey, token);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { 'content-type': 'application/json' } : {}),
      ...(accessToken() ? { authorization: `Bearer ${accessToken()}` } : {}),
      ...(options.headers ?? {})
    }
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.message ?? data?.error ?? `HTTP ${response.status}`);
  }
  return data;
}

async function login() {
  if (config.noSecurity) {
    await devLogin();
    return;
  }

  if (!config.authorizationEndpoint || !config.clientId) {
    alert('OIDC is not configured. Set OIDC_DISCOVERY_URI and OIDC_CLIENT_ID.');
    return;
  }

  const verifier = randomString(48);
  const state = randomString(24);
  const challenge = base64Url(await sha256(verifier));
  sessionStorage.setItem(verifierStorageKey, verifier);
  sessionStorage.setItem(stateStorageKey, state);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: config.scopes.join(' '),
    code_challenge: challenge,
    code_challenge_method: 'S256',
    state
  });

  location.assign(`${config.authorizationEndpoint}?${params.toString()}`);
}

async function handleCallback() {
  const params = new URLSearchParams(location.search);
  const code = params.get('code');
  const error = params.get('error');
  if (error) {
    throw new Error(params.get('error_description') || error);
  }
  if (!code) return;

  const verifier = sessionStorage.getItem(verifierStorageKey);
  const expectedState = sessionStorage.getItem(stateStorageKey);
  if (!verifier) {
    throw new Error('Login session expired. Start login again.');
  }
  if (!expectedState || params.get('state') !== expectedState) {
    throw new Error('Login state mismatch. Start login again.');
  }

  const token = await redeemAuthorizationCode({
    code,
    verifier,
    redirectUri: config.redirectUri
  });

  if (!token.access_token) {
    throw new Error('Token endpoint did not return an access token.');
  }

  setAccessToken(token.access_token);
  sessionStorage.removeItem(verifierStorageKey);
  sessionStorage.removeItem(stateStorageKey);
  history.replaceState({}, document.title, '/');
}

async function redeemAuthorizationCode({ code, verifier, redirectUri }) {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: config.clientId,
    redirect_uri: redirectUri,
    code,
    code_verifier: verifier
  });

  const response = await fetch(config.tokenEndpoint, {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'content-type': 'application/x-www-form-urlencoded'
    },
    body
  });
  const token = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(token.error_description || token.error || `Token endpoint returned HTTP ${response.status}`);
  }
  return token;
}

async function devLogin() {
  const token = await api('/api/dev-token', { method: 'POST' });
  setAccessToken(token.access_token);
  await render();
}

function showHome() {
  els.landingView.classList.add('hidden');
  els.homeView.classList.remove('hidden');
  setActiveTab('overview');
  els.loginButton.classList.add('hidden');
  els.heroLoginButton.classList.add('hidden');
  els.devLoginButton.classList.add('hidden');
  els.logoutButton.classList.remove('hidden');
}

function showLanding() {
  els.homeView.classList.add('hidden');
  els.landingView.classList.remove('hidden');
  els.loginButton.classList.remove('hidden');
  if (config.noSecurity) {
    els.devLoginButton.classList.remove('hidden');
  }
  els.logoutButton.classList.add('hidden');
  els.firstNameGreeting.textContent = '';
  els.usernameDisplay.textContent = '';
}

function firstNameFromProfile(profile) {
  const claimName = profile?.claims?.givenName || profile?.claims?.name || profile?.claims?.username;
  if (!claimName) return '';
  return String(claimName).trim().split(/\s+/)[0];
}

function usernameFromProfile(profile) {
  return (
    profile?.claims?.username
    || profile?.claims?.email
    || profile?.claims?.preferred_username
    || profile?.subject
    || ''
  );
}

function appendMessage(role, text) {
  const node = document.createElement('div');
  node.className = `message ${role}`;
  node.textContent = text;
  els.chatMessages.appendChild(node);
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

async function sendChat(message) {
  appendMessage('user', message);
  appendMessage('agent', 'Checking your account...');
  const pending = els.chatMessages.lastElementChild;
  try {
    const response = await api('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message })
    });
    pending.textContent = response.message;
    await loadTokenHistory();
  } catch (error) {
    pending.textContent = error.message;
    await loadTokenHistory();
  }
}

async function loadTokenHistory() {
  if (!accessToken()) return;
  try {
    const { events = [] } = await api('/api/token-history');
    renderTokenHistory(events);
  } catch (error) {
    els.tokenHistory.innerHTML = '';
    const node = document.createElement('div');
    node.className = 'token-empty';
    node.textContent = error.message;
    els.tokenHistory.appendChild(node);
  }
}

function renderTokenHistory(events) {
  els.tokenHistory.innerHTML = '';
  if (!events.length) {
    const empty = document.createElement('div');
    empty.className = 'token-empty';
    empty.textContent = 'No token events yet.';
    els.tokenHistory.appendChild(empty);
    return;
  }

  for (const step of buildTokenJourney(events)) {
    const item = document.createElement('article');
    const isOpen = step.number === openTokenJourneyStep;
    item.className = `token-journey-step ${step.available ? '' : 'missing'} ${isOpen ? 'open' : ''}`;
    const header = document.createElement('button');
    header.type = 'button';
    header.className = 'token-journey-header';
    header.setAttribute('aria-expanded', String(isOpen));
    header.innerHTML = `<span>${step.number}</span><div><strong>${escapeHtml(step.title)}</strong><small>${escapeHtml(step.subtitle)}</small></div><i>${isOpen ? 'Hide' : 'Open'}</i>`;
    header.addEventListener('click', () => {
      openTokenJourneyStep = isOpen ? 0 : step.number;
      renderTokenHistory(events);
    });
    item.appendChild(header);

    if (!step.available) {
      if (isOpen) {
        const empty = document.createElement('p');
        empty.className = 'token-step-empty';
        empty.textContent = 'Waiting for this hop.';
        item.appendChild(empty);
      }
      els.tokenHistory.appendChild(item);
      continue;
    }

    const details = document.createElement('div');
    details.className = `token-step-details ${isOpen ? '' : 'hidden'}`;
    for (const token of step.tokens.filter((item) => item.claims)) {
      const card = document.createElement('section');
      card.className = 'token-claims-card';
      const title = document.createElement('div');
      title.className = 'token-claims-card-title';
      title.innerHTML = `<strong>${escapeHtml(token.label)}</strong>`;
      const summary = document.createElement('div');
      summary.className = 'token-summary-grid';
      summary.innerHTML = tokenSummaryRows(tokenSummary(token.claims))
        .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || 'none')}</strong></div>`)
        .join('');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ghost compact';
      button.textContent = 'View JSON claims';
      button.addEventListener('click', () => showClaimsModal(token.label, token.claims));
      title.appendChild(button);
      card.append(title, summary);
      details.appendChild(card);
    }
    if (!details.childElementCount) {
      const empty = document.createElement('p');
      empty.className = 'token-step-empty';
      empty.textContent = 'No token claims captured for this hop yet.';
      details.appendChild(empty);
    }
    item.appendChild(details);
    els.tokenHistory.appendChild(item);
  }
}

function buildTokenJourney(events) {
  const browserTokenClaims = decodeJwtClaims(accessToken());
  const apiToken = latest(events, 'portal-api', 'api-token-accepted') || latest(events, 'portal-api', 'api-token-received');
  const apiToAgentExchange = latest(events, 'portal-api', 'agent-token-exchange-success');
  const apiToAgentCall = latest(events, 'portal-agent', 'call-agent-request');
  const agentToMcpExchange = latest(events, 'agent-mcp', 'mcp-token-exchange-success');
  const agentToMcpCall = latest(events, 'agent-mcp', 'connect-start') || latest(events, 'agent-mcp', 'tool-call-start');

  return [
    {
      number: 1,
      title: 'Web Portal -> API token',
      subtitle: 'Browser access token received by the portal API',
      available: Boolean(browserTokenClaims || apiToken?.token),
      tokens: [{ label: 'API token claims', claims: browserTokenClaims || claimsOf(apiToken?.token) }]
    },
    {
      number: 2,
      title: 'API to Agent token exchange',
      subtitle: 'Portal API exchanges the browser token with its JWT-SVID actor token',
      available: Boolean(apiToAgentExchange),
      tokens: [
        { label: 'Subject token claims', claims: claimsOf(apiToAgentExchange?.subjectToken) },
        { label: 'Actor token claims', claims: claimsOf(apiToAgentExchange?.actorToken) },
        { label: 'Issued agent token claims', claims: claimsOf(apiToAgentExchange?.issuedToken) || claimsOf(apiToAgentExchange?.response?.accessToken) }
      ]
    },
    {
      number: 3,
      title: 'API -> Agent token',
      subtitle: 'Portal API calls the agent with the issued agent token',
      available: Boolean(apiToAgentCall?.token),
      tokens: [{ label: 'Agent bearer token claims', claims: claimsOf(apiToAgentCall?.token) }]
    },
    {
      number: 4,
      title: 'Agent to MCP token exchange',
      subtitle: 'Agent exchanges the agent token with its JWT-SVID actor token',
      available: Boolean(agentToMcpExchange),
      tokens: [
        { label: 'Subject token claims', claims: claimsOf(agentToMcpExchange?.subjectToken) },
        { label: 'Actor token claims', claims: claimsOf(agentToMcpExchange?.actorToken) },
        { label: 'Issued MCP token claims', claims: claimsOf(agentToMcpExchange?.issuedToken) || claimsOf(agentToMcpExchange?.response?.accessToken) }
      ]
    },
    {
      number: 5,
      title: 'Agent -> MCP token',
      subtitle: 'Agent calls MCP with the issued MCP token',
      available: Boolean(agentToMcpCall?.token),
      tokens: [{ label: 'MCP bearer token claims', claims: claimsOf(agentToMcpCall?.token) }]
    }
  ];
}

function latest(events, component, eventName) {
  return [...events].reverse().find((event) => event.component === component && event.event === eventName);
}

function claimsOf(summary) {
  return summary?.claims ?? null;
}

function tokenSummary(claims) {
  return {
    subject: claims.sub,
    actor: claims.act?.sub,
    audience: formatClaimValue(claims.aud),
    scopes: claims.scope
  };
}

function tokenSummaryRows(summary) {
  return [
    ['Subject', summary.subject],
    ['Actor', summary.actor],
    ['Audience', summary.audience],
    ['Scopes', summary.scopes]
  ];
}

function formatClaimValue(value) {
  return Array.isArray(value) ? value.join(' ') : value;
}

function decodeJwtClaims(token) {
  if (!token || !token.includes('.')) return null;
  try {
    const payload = token.split('.')[1];
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(normalized.length + ((4 - normalized.length % 4) % 4), '=');
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

function showClaimsModal(title, claims) {
  els.claimsModalTitle.textContent = title;
  els.claimsModalBody.textContent = JSON.stringify(claims, null, 2);
  els.claimsModal.classList.remove('hidden');
}

function hideClaimsModal() {
  els.claimsModal.classList.add('hidden');
}

function setActiveTab(tab) {
  const isTokenFlow = tab === 'token-flow';
  els.overviewPanel.classList.toggle('hidden', isTokenFlow);
  els.tokenFlowPanel.classList.toggle('hidden', !isTokenFlow);
  for (const button of els.tabButtons) {
    const active = button.dataset.tab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  }
  if (isTokenFlow) {
    loadTokenHistory();
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

async function render() {
  if (!accessToken()) {
    showLanding();
    return;
  }

  try {
    const profile = await api('/api/me');
    const firstName = firstNameFromProfile(profile);
    els.firstNameGreeting.textContent = firstName ? `, ${firstName}` : '';
    const username = usernameFromProfile(profile);
    els.usernameDisplay.textContent = username ? `Signed in as ${username}` : '';
    showHome();
    await loadTokenHistory();
  } catch {
    sessionStorage.removeItem(tokenStorageKey);
    showLanding();
  }
}

els.loginButton.addEventListener('click', login);
els.heroLoginButton.addEventListener('click', login);
els.devLoginButton.addEventListener('click', devLogin);
els.logoutButton.addEventListener('click', () => {
  sessionStorage.clear();
  showLanding();
});
els.openChatButton.addEventListener('click', () => {
  els.chatDrawer.classList.remove('hidden');
  if (!els.chatMessages.childElementCount) {
    appendMessage('agent', 'Hi, I can help with your plan, usage, devices, bill, and payments.');
  }
});
els.closeChatButton.addEventListener('click', () => els.chatDrawer.classList.add('hidden'));
els.refreshTokenHistoryButton.addEventListener('click', loadTokenHistory);
els.closeClaimsModalButton.addEventListener('click', hideClaimsModal);
els.claimsModal.addEventListener('click', (event) => {
  if (event.target === els.claimsModal) {
    hideClaimsModal();
  }
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    hideClaimsModal();
  }
});
for (const button of els.tabButtons) {
  button.addEventListener('click', () => setActiveTab(button.dataset.tab));
}
els.chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message) return;
  els.chatInput.value = '';
  await sendChat(message);
});

if (config.noSecurity) {
  els.devLoginButton.classList.remove('hidden');
}

handleCallback()
  .then(render)
  .catch((error) => {
    console.error(error);
    alert(error.message);
    showLanding();
  });
