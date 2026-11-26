// State Management
let calendarEvents = [];
let hashedRecords = [];
let currentView = "chat";

// Multi-User State Management
let currentUserId = localStorage.getItem("calendar_ai_user_id");
if (!currentUserId) {
    currentUserId = "guest_" + Math.random().toString(36).substring(2, 10);
    localStorage.setItem("calendar_ai_user_id", currentUserId);
}
let currentUserEmail = localStorage.getItem("calendar_ai_user_email") || null;
let currentUserName = localStorage.getItem("calendar_ai_user_name") || null;
let currentUserAvatar = localStorage.getItem("calendar_ai_user_avatar") || null;

// Helper: Authenticated fetch wrapper injecting multi-user headers
function authFetch(url, options = {}) {
    options = options || {};
    options.headers = options.headers || {};
    const uid = currentUserEmail || currentUserId || "guest";
    if (options.headers instanceof Headers) {
        options.headers.set("X-User-Id", uid);
        if (currentUserEmail) options.headers.set("X-User-Email", currentUserEmail);
    } else {
        options.headers["X-User-Id"] = uid;
        if (currentUserEmail) options.headers["X-User-Email"] = currentUserEmail;
    }
    return fetch(url, options);
}

// Event date & time extraction helpers (supports both nested Google objects and flat Supabase DB rows)
function getEventStartRaw(ev) {
    if (!ev) return "";
    return ev.start?.dateTime || ev.start?.date || ev.start_time || ev.date_time || "";
}

function getEventEndRaw(ev) {
    if (!ev) return "";
    return ev.end?.dateTime || ev.end?.date || ev.end_time || getEventStartRaw(ev);
}

function getEventYmd(ev) {
    const raw = getEventStartRaw(ev);
    if (!raw) return "";
    return raw.substring(0, 10);
}

// Calendar Grid State
let calCurrentYear = new Date().getFullYear();
let calCurrentMonth = new Date().getMonth(); // 0-indexed (0 = Jan, 9 = Oct)
let calSelectedDateStr = formatYmd(new Date());
let calViewMode = "grid"; // "grid" or "agenda"

// DOM Elements - Navigation
const navBtnChat = document.getElementById("navBtnChat");
const navBtnCalendar = document.getElementById("navBtnCalendar");
const navBtnHashedDB = document.getElementById("navBtnHashedDB");
const navBtnSettings = document.getElementById("navBtnSettings");

const viewChat = document.getElementById("viewChat");
const viewCalendar = document.getElementById("viewCalendar");
const viewHashedDB = document.getElementById("viewHashedDB");
const viewSettings = document.getElementById("viewSettings");

// Badges & Labels
const navEventCountBadge = document.getElementById("navEventCountBadge");
const calendarViewCountPill = document.getElementById("calendarViewCountPill");
const googleStatusLabel = document.getElementById("googleStatusLabel");
const googleStatusIconDot = document.getElementById("googleStatusIconDot");
const googleStatusBadgeBig = document.getElementById("googleStatusBadgeBig");
const sidebarAiModel = document.getElementById("sidebarAiModel");

// Chat Elements
const chatMessages = document.getElementById("chatMessages");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const btnSendChat = document.getElementById("btnSendChat");
const chatUserBadge = document.getElementById("chatUserBadge");
const btnClearChat = document.getElementById("btnClearChat");

// Calendar View Elements
const calMonthYearTitle = document.getElementById("calMonthYearTitle");
const btnPrevMonth = document.getElementById("btnPrevMonth");
const btnNextMonth = document.getElementById("btnNextMonth");
const btnToday = document.getElementById("btnToday");
const btnToggleGridView = document.getElementById("btnToggleGridView");
const btnToggleListView = document.getElementById("btnToggleListView");
const calGridSection = document.getElementById("calGridSection");
const calAgendaSection = document.getElementById("calAgendaSection");
const calGridCells = document.getElementById("calGridCells");
const calSelectedDayHeading = document.getElementById("calSelectedDayHeading");
const calSelectedDayEventsList = document.getElementById("calSelectedDayEventsList");
const btnAddEventForSelectedDay = document.getElementById("btnAddEventForSelectedDay");
const calendarEventsList = document.getElementById("calendarEventsList");
const btnOpenCreateEvent = document.getElementById("btnOpenCreateEvent");
const hashedTableFullContainer = document.getElementById("hashedTableFullContainer");
const btnRefreshHashedDB = document.getElementById("btnRefreshHashedDB");
const btnSidebarSync = document.getElementById("btnSidebarSync");

// Event Modal Elements
const eventModal = document.getElementById("eventModal");
const modalTitle = document.getElementById("modalTitle");
const eventForm = document.getElementById("eventForm");
const modalEventId = document.getElementById("modalEventId");
const modalSummary = document.getElementById("modalSummary");
const modalEventDate = document.getElementById("modalEventDate");
const modalOptionalDetails = document.getElementById("modalOptionalDetails");
const modalEventTime = document.getElementById("modalEventTime");
const modalStartTime = document.getElementById("modalStartTime");
const modalEndTime = document.getElementById("modalEndTime");
const modalPriority = document.getElementById("modalPriority");
const modalLocation = document.getElementById("modalLocation");
const modalDescription = document.getElementById("modalDescription");
const btnCloseModal = document.getElementById("btnCloseModal");
const btnCancelModal = document.getElementById("btnCancelModal");

// User Profile & Google OAuth Elements
const btnGoogleSignInMain = document.getElementById("btnGoogleSignInMain");
const googleSignInBtnText = document.getElementById("googleSignInBtnText");
const userProfileCard = document.getElementById("userProfileCard");
const userAvatarImg = document.getElementById("userAvatarImg");
const userAvatarFallback = document.getElementById("userAvatarFallback");
const userDisplayName = document.getElementById("userDisplayName");
const userEmailAddress = document.getElementById("userEmailAddress");
const btnSignOut = document.getElementById("btnSignOut");

const supabaseStatusBadge = document.getElementById("supabaseStatusBadge");
const inputSupabaseUrl = document.getElementById("inputSupabaseUrl");
const inputSupabaseKey = document.getElementById("inputSupabaseKey");
const btnApplySupabase = document.getElementById("btnApplySupabase");
const btnCopySqlSchema = document.getElementById("btnCopySqlSchema");

const btnConnectGoogleOAuth = document.getElementById("btnConnectGoogleOAuth");
const btnDisconnectGoogle = document.getElementById("btnDisconnectGoogle");
const inputCredentialsFile = document.getElementById("inputCredentialsFile");
const btnQuickConnectGoogle = document.getElementById("btnQuickConnectGoogle");
const inputGroqKey = document.getElementById("inputGroqKey");
const btnApplyGroqKey = document.getElementById("btnApplyGroqKey");

const SUPABASE_PROJECT_URL = "https://xsiakjocrgtskarwzxse.supabase.co";

let supabaseClient = null;
let authListenerInitialized = false;

// Initialization
document.addEventListener("DOMContentLoaded", async () => {
    setupNavigation();
    setupChat();
    setupSpeechRecognition();
    setupCalendarHandlers();
    setupGoogleAuthHandlers();
    setupChangePasswordHandlers();

    // 1. Fetch system status (and configure Supabase client if available)
    await fetchStatus();

    // 2. Resolve auth state immediately before loading data
    await checkInitialAuthState();

    // 3. Load all user data
    await reloadAllUserData();
});

async function checkInitialAuthState() {
    // 0. Check for OAuth error in URL redirect
    const urlParams = new URLSearchParams(window.location.search);
    const errorDesc = urlParams.get('error_description') || urlParams.get('error');
    if (errorDesc) {
        console.warn("OAuth error received in URL:", errorDesc);
        window.history.replaceState({}, document.title, window.location.pathname);
        showToast("Google OAuth Error: " + decodeURIComponent(errorDesc).replace(/\+/g, ' '));
    }

    // 1. Check for hash parameters (#access_token=...) from Google OAuth (works directly without client dependency)
    if (window.location.hash && window.location.hash.includes("access_token")) {
        console.log("OAuth access_token in URL hash, resolving session...");
        try {
            const hashStr = window.location.hash.substring(1);
            const hashParams = new URLSearchParams(hashStr);
            const accessToken = hashParams.get("access_token");
            const refreshToken = hashParams.get("refresh_token");
            const providerToken = hashParams.get("provider_token");
            const providerRefreshToken = hashParams.get("provider_refresh_token");

            if (accessToken) {
                // Extract JWT payload directly so user details are guaranteed instantly
                try {
                    const base64Url = accessToken.split('.')[1];
                    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
                    const jsonPayload = decodeURIComponent(atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
                    const payload = JSON.parse(jsonPayload);
                    if (payload && payload.email) {
                        applyUserSession({
                            id: payload.sub || payload.email,
                            email: payload.email,
                            user_metadata: payload.user_metadata || {
                                full_name: payload.full_name || payload.name || payload.email.split('@')[0],
                                avatar_url: payload.avatar_url || payload.picture || ""
                            }
                        });
                        localStorage.setItem("supabase_auth_token", accessToken);
                        if (refreshToken) localStorage.setItem("supabase_refresh_token", refreshToken);
                    }
                } catch (parseErr) {
                    console.warn("JWT parse note:", parseErr);
                }

                if (providerToken) {
                    localStorage.setItem("google_provider_token", providerToken);
                }
                if (providerRefreshToken) {
                    localStorage.setItem("google_provider_refresh_token", providerRefreshToken);
                }

                // Sync Google Calendar live on backend if provider_token is available
                if (providerToken) {
                    console.log("Connecting backend Google Calendar via provider_token...");
                    try {
                        const tokenRes = await fetch("/api/calendar/auth/google_token", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                provider_token: providerToken,
                                user_email: currentUserEmail,
                                refresh_token: providerRefreshToken || null
                            })
                        });
                        const tData = await tokenRes.json();
                        if (tokenRes.ok) {
                            console.log("Live Google Calendar connected on backend:", tData);
                            const count = tData.imported_count || 0;
                            showToast(`🟢 Connected live Google Calendar for ${currentUserEmail}! Fetched ${count} events.`, 4500);
                            await loadCalendarEvents();
                            await loadHashedTable();
                        } else {
                            console.warn("Backend Google Calendar connect note:", tData);
                            showToast(`Google Calendar note: ${tData.detail || 'Authorization needed'}`, 8000);
                        }
                    } catch (e) {
                        console.warn("Backend Google Calendar connect note:", e);
                    }
                    syncGoogleCalendarFromToken(providerToken);
                }

                // Clean URL bar
                window.history.replaceState({}, document.title, window.location.pathname);
                showToast(`Signed in as ${currentUserEmail || 'Google User'}`);
                await fetchStatus();
                await reloadAllUserData();
                return;
            }
        } catch (err) {
            console.warn("Hash session check error:", err);
        }
    }

    // 2. Check for PKCE ?code= in URL redirect from Google (if client available)
    const code = urlParams.get('code');
    if (code && supabaseClient) {
        console.log("OAuth code detected in URL, exchanging for session...");
        try {
            const { data, error } = await supabaseClient.auth.exchangeCodeForSession(code);
            if (data && data.session && data.session.user) {
                applyUserSession(data.session.user);
                if (data.session.provider_token) {
                    localStorage.setItem("google_provider_token", data.session.provider_token);
                    if (data.session.provider_refresh_token) {
                        localStorage.setItem("google_provider_refresh_token", data.session.provider_refresh_token);
                    }
                    syncGoogleCalendarFromToken(data.session.provider_token);
                }
                window.history.replaceState({}, document.title, window.location.pathname);
                showToast(`Signed in as ${data.session.user.email}`);
                await fetchStatus();
                await reloadAllUserData();
                return;
            }
        } catch (err) {
            console.warn("exchangeCodeForSession exception:", err);
        }
    }

    // 3. Regular active session check if supabaseClient is connected
    if (supabaseClient) {
        initSupabaseAuthListener();
        try {
            const { data: { session }, error } = await supabaseClient.auth.getSession();
            if (session && session.user) {
                applyUserSession(session.user);
                return;
            }
        } catch (e) {
            console.warn("Session retrieval note:", e);
        }
    }

    if (currentUserEmail) {
        updateUserProfileUI(true);
    } else {
        updateUserProfileUI(false);
    }
}

function applyUserSession(user) {
    currentUserEmail = user.email || "";
    currentUserId = user.email || user.id;
    currentUserName = user.user_metadata?.full_name || user.user_metadata?.name || (user.email ? user.email.split("@")[0] : "User");
    currentUserAvatar = user.user_metadata?.avatar_url || user.user_metadata?.picture || "";

    localStorage.setItem("calendar_ai_user_id", currentUserId);
    localStorage.setItem("calendar_ai_user_email", currentUserEmail);
    if (currentUserName) localStorage.setItem("calendar_ai_user_name", currentUserName);
    if (currentUserAvatar) localStorage.setItem("calendar_ai_user_avatar", currentUserAvatar);

    updateUserProfileUI(true);
}

// Navigation Handling
function setupNavigation() {
    if (navBtnChat) navBtnChat.addEventListener("click", () => switchView("chat"));
    if (navBtnCalendar) navBtnCalendar.addEventListener("click", () => switchView("calendar"));
}

function switchView(viewName) {
    currentView = viewName;
    
    // Hide all views
    if (viewChat) viewChat.classList.add("hidden");
    if (viewCalendar) viewCalendar.classList.add("hidden");

    // Reset active class
    [navBtnChat, navBtnCalendar].forEach(btn => {
        if (btn) btn.classList.remove("active");
    });

    if (viewName === "chat") {
        if (viewChat) viewChat.classList.remove("hidden");
        if (navBtnChat) navBtnChat.classList.add("active");
    } else if (viewName === "calendar") {
        if (viewCalendar) viewCalendar.classList.remove("hidden");
        if (navBtnCalendar) navBtnCalendar.classList.add("active");
        renderFullCalendar();
    }
}

// Multi-User UI Updates & State Sync
function updateUserProfileUI(isLoggedIn) {
    const modalUserIndicator = document.getElementById("modalUserIndicator");
    if (isLoggedIn && currentUserEmail) {
        if (btnGoogleSignInMain) btnGoogleSignInMain.classList.add("hidden");
        if (userProfileCard) userProfileCard.classList.remove("hidden");
        
        if (userDisplayName) userDisplayName.innerText = currentUserName || currentUserEmail.split("@")[0];
        if (userEmailAddress) userEmailAddress.innerText = currentUserEmail;
        
        if (currentUserAvatar && userAvatarImg) {
            userAvatarImg.src = currentUserAvatar;
            userAvatarImg.classList.remove("hidden");
            if (userAvatarFallback) userAvatarFallback.classList.add("hidden");
        } else if (userAvatarFallback) {
            userAvatarFallback.innerText = (currentUserName || currentUserEmail || "U")[0].toUpperCase();
            userAvatarFallback.classList.remove("hidden");
            if (userAvatarImg) userAvatarImg.classList.add("hidden");
        }
        
        if (chatUserBadge) {
            chatUserBadge.innerText = currentUserEmail;
            chatUserBadge.className = "text-[10px] bg-sage-100 text-sage-800 border border-sage-200 px-2 py-0.5 rounded-md font-mono font-medium";
        }
        if (modalUserIndicator) {
            modalUserIndicator.innerText = currentUserEmail;
        }
    } else {
        if (btnGoogleSignInMain) btnGoogleSignInMain.classList.remove("hidden");
        if (userProfileCard) userProfileCard.classList.add("hidden");
        if (chatUserBadge) {
            chatUserBadge.innerText = "Guest Mode";
            chatUserBadge.className = "text-[10px] bg-cream-200 text-cream-800 px-2 py-0.5 rounded-md font-mono";
        }
        if (modalUserIndicator) {
            modalUserIndicator.innerText = "Guest";
        }
    }

    const welcomeUserNameEl = document.getElementById("welcomeUserName");
    if (welcomeUserNameEl) {
        let rawName = currentUserName || (currentUserEmail ? currentUserEmail.split("@")[0] : "Guest");
        let formattedName = rawName ? (rawName.charAt(0).toUpperCase() + rawName.slice(1)) : "Guest";
        welcomeUserNameEl.innerText = formattedName;
    }
}

async function reloadAllUserData() {
    await loadCalendarEvents();
    await loadHashedTable();
    await loadChatHistory();
}

function initSupabaseAuthListener() {
    if (!supabaseClient || authListenerInitialized) return;
    authListenerInitialized = true;

    supabaseClient.auth.onAuthStateChange(async (event, session) => {
        if (session && session.user) {
            applyUserSession(session.user);
            showToast(`Signed in as ${session.user.email}`);

            if (session.provider_token) {
                localStorage.setItem("google_provider_token", session.provider_token);
                if (session.provider_refresh_token) {
                    localStorage.setItem("google_provider_refresh_token", session.provider_refresh_token);
                }
                await syncGoogleCalendarFromToken(session.provider_token);
            }
            await reloadAllUserData();
        } else if (event === "SIGNED_OUT") {
            handleSignOutCleanup();
            showToast("Signed out. Switched to guest workspace.");
            await reloadAllUserData();
        }
    });
}

function handleSignOutCleanup() {
    localStorage.removeItem("calendar_ai_user_email");
    localStorage.removeItem("calendar_ai_user_name");
    localStorage.removeItem("calendar_ai_user_avatar");
    currentUserEmail = null;
    currentUserName = null;
    currentUserAvatar = null;
    currentUserId = "guest_" + Math.random().toString(36).substring(2, 10);
    localStorage.setItem("calendar_ai_user_id", currentUserId);
    updateUserProfileUI(false);
}

async function syncGoogleCalendarFromToken(providerToken) {
    if (!providerToken) return;
    try {
        // First, notify backend to connect live Google Calendar and index events
        try {
            await fetch("/api/calendar/auth/google_token", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    provider_token: providerToken,
                    user_email: currentUserEmail,
                    refresh_token: localStorage.getItem("google_provider_refresh_token") || null
                })
            });
        } catch (be) {
            console.warn("Backend token connect notice:", be);
        }

        // Also fetch directly from Google API (1 year past to future) to ensure comprehensive sync
        const pastDate = new Date();
        pastDate.setFullYear(pastDate.getFullYear() - 1);
        const url = `https://www.googleapis.com/calendar/v3/calendars/primary/events?timeMin=${pastDate.toISOString()}&maxResults=250&singleEvents=true&orderBy=startTime`;
        const res = await fetch(url, {
            headers: { "Authorization": `Bearer ${providerToken}` }
        });
        if (!res.ok) return;
        const gdata = await res.json();
        const items = gdata.items || [];
        if (items.length === 0) return;

        const mappedEvents = items.map(it => ({
            id: it.id || `gcal-${Math.random().toString(36).substring(2, 9)}`,
            summary: it.summary || "Untitled Event",
            description: it.description || "",
            location: it.location || "",
            priority: "medium",
            start: it.start,
            end: it.end,
            source: "google"
        }));

        const importRes = await authFetch("/api/calendar/google_import", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ events: mappedEvents })
        });
        if (importRes.ok) {
            showToast(`Imported ${mappedEvents.length} events from Google Calendar!`);
            await loadCalendarEvents();
            await loadHashedTable();
        }
    } catch (e) {
        console.warn("Google calendar token sync notice:", e);
    }
}

function startGoogleCalendarOAuth() {
    const redirectUri = window.location.origin + window.location.pathname;
    const scopes = encodeURIComponent("https://www.googleapis.com/auth/calendar https://www.googleapis.com/auth/calendar.events email profile");
    const oauthUrl = `${SUPABASE_PROJECT_URL}/auth/v1/authorize?provider=google&redirect_to=${encodeURIComponent(redirectUri)}&scopes=${scopes}&prompt=consent&access_type=offline`;
    
    showToast("Opening Google to connect your Google Calendar...", 3000);
    setTimeout(() => {
        window.location.href = oauthUrl;
    }, 250);
}

async function disconnectGoogleCalendar() {
    if (!confirm("Disconnect Google Calendar? The assistant will switch back to local simulated store.")) return;
    try {
        localStorage.removeItem("google_provider_token");
        localStorage.removeItem("google_provider_refresh_token");
        await fetch("/api/calendar/auth/disconnect", { method: "POST" });
        showToast("Disconnected Google Calendar.");
        await fetchStatus();
        await loadCalendarEvents();
        await loadHashedTable();
    } catch (e) {
        console.error("Disconnect error:", e);
    }
}

// Fetch System Status
async function fetchStatus() {
    try {
        const res = await authFetch("/api/status");
        const data = await res.json();
        
        // Initialize Supabase Client if configured
        if (window.supabase && data.supabase_url && data.supabase_key && !data.supabase_key.startsWith("sb_secret_") && !supabaseClient) {
            try {
                supabaseClient = window.supabase.createClient(data.supabase_url, data.supabase_key);
                initSupabaseAuthListener();
            } catch (err) {
                console.warn("Supabase init error:", err);
            }
        }
        
        // Auto-reconnect if client has saved google token but backend was restarted
        if (!data.google_calendar_connected && localStorage.getItem("google_provider_token") && !window._retriedTokenAuth) {
            window._retriedTokenAuth = true;
            try {
                const tokenRes = await fetch("/api/calendar/auth/google_token", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        provider_token: localStorage.getItem("google_provider_token"),
                        user_email: currentUserEmail,
                        refresh_token: localStorage.getItem("google_provider_refresh_token") || null
                    })
                });
                if (tokenRes.ok) {
                    const freshStatus = await (await authFetch("/api/status")).json();
                    Object.assign(data, freshStatus);
                    await loadCalendarEvents();
                    await loadHashedTable();
                }
            } catch (retryErr) {
                console.warn("Auto-reconnect token note:", retryErr);
            }
        }

        const btnSidebarConnectGoogle = document.getElementById("btnSidebarConnectGoogle");
        const btnSidebarDisconnectGoogle = document.getElementById("btnSidebarDisconnectGoogle");

        if (data.google_calendar_connected) {
            if (googleStatusLabel) googleStatusLabel.innerText = "Live: " + (data.google_user_email || "Connected");
            if (googleStatusIconDot) googleStatusIconDot.className = "w-2 h-2 rounded-full bg-sage-500 shrink-0 animate-pulse";
            if (googleStatusBadgeBig) {
                googleStatusBadgeBig.innerHTML = `
                    <span class="w-1.5 h-1.5 rounded-full bg-sage-500 animate-pulse"></span>
                    <span>Connected: ${data.google_user_email || "Google Calendar"}</span>
                    <i class="fa-solid fa-link-slash text-[10px] ml-1 text-sage-600 hover:text-rose-600 cursor-pointer" title="Disconnect Calendar"></i>
                `;
                googleStatusBadgeBig.className = "text-[11px] px-2.5 py-1 rounded-full font-semibold bg-sage-100 text-sage-800 border border-sage-200 flex items-center gap-1.5 shadow-2xs transition";
                googleStatusBadgeBig.onclick = (e) => {
                    if (e.target.closest(".fa-link-slash")) {
                        disconnectGoogleCalendar();
                    }
                };
            }
            if (googleSignInBtnText) googleSignInBtnText.innerText = data.google_user_email || "Google Connected";
            if (btnSidebarConnectGoogle) btnSidebarConnectGoogle.classList.add("hidden");
            if (btnSidebarDisconnectGoogle) {
                btnSidebarDisconnectGoogle.classList.remove("hidden");
                btnSidebarDisconnectGoogle.onclick = () => disconnectGoogleCalendar();
            }
        } else {
            if (googleStatusLabel) googleStatusLabel.innerText = "Simulated Store";
            if (googleStatusIconDot) googleStatusIconDot.className = "w-2 h-2 rounded-full bg-amber-500 shrink-0";
            if (googleStatusBadgeBig) {
                googleStatusBadgeBig.innerHTML = `
                    <i class="fa-brands fa-google text-amber-700"></i>
                    <span>Simulated Store (Connect Google)</span>
                `;
                googleStatusBadgeBig.className = "text-[11px] px-2.5 py-1 rounded-full font-bold flex items-center gap-1.5 bg-amber-100 hover:bg-amber-200 text-amber-900 border border-amber-300 shadow-2xs transition active:scale-95 cursor-pointer";
                googleStatusBadgeBig.onclick = () => startGoogleCalendarOAuth();
            }
            if (googleSignInBtnText) googleSignInBtnText.innerText = "Sign in with Google";
            if (btnSidebarConnectGoogle) {
                btnSidebarConnectGoogle.classList.remove("hidden");
                btnSidebarConnectGoogle.onclick = () => startGoogleCalendarOAuth();
            }
            if (btnSidebarDisconnectGoogle) {
                btnSidebarDisconnectGoogle.classList.add("hidden");
            }
        }

        // Supabase Status
        const sidebarDbStatus = document.getElementById("sidebarDbStatus");
        if (data.supabase_connected) {
            if (sidebarDbStatus) {
                sidebarDbStatus.innerText = "Supabase DB";
                sidebarDbStatus.className = "font-bold text-sage-700 text-[10px]";
            }
            if (supabaseStatusBadge) {
                supabaseStatusBadge.innerText = "Connected to Supabase PostgreSQL";
                supabaseStatusBadge.className = "text-xs px-3 py-1 rounded-full font-semibold bg-sage-100 text-sage-800 border border-sage-200";
            }
            if (inputSupabaseUrl && data.supabase_url) {
                inputSupabaseUrl.value = data.supabase_url;
            }
        } else {
            if (sidebarDbStatus) {
                sidebarDbStatus.innerText = "Local In-Memory";
                sidebarDbStatus.className = "font-bold text-cream-700 text-[10px]";
            }
            if (supabaseStatusBadge) {
                supabaseStatusBadge.innerText = "Local In-Memory Mode";
                supabaseStatusBadge.className = "text-xs px-3 py-1 rounded-full font-semibold bg-cream-100 text-cream-700 border border-cream-200";
            }
        }

        if (sidebarAiModel) {
            if (data.groq_configured) {
                sidebarAiModel.innerText = "Groq (120B Fast)";
                sidebarAiModel.className = "text-sage-700 text-[11px] font-bold";
            } else {
                sidebarAiModel.innerText = "Local Engine";
                sidebarAiModel.className = "text-cream-700 text-[11px] font-medium";
            }
        }
    } catch (e) {
        console.warn("fetchStatus error", e);
    }
}

// Load Calendar Events
async function loadCalendarEvents() {
    try {
        const res = await authFetch("/api/calendar/events");
        const data = await res.json();
        calendarEvents = data.events || [];
        if (navEventCountBadge) navEventCountBadge.innerText = calendarEvents.length;
        if (calendarViewCountPill) calendarViewCountPill.innerText = `${calendarEvents.length} events`;
        renderFullCalendar();
    } catch (e) {
        if (calendarEventsList) calendarEventsList.innerHTML = `<p class="text-rose-600 text-xs">Error loading calendar events.</p>`;
    }
}

// ==============================================
// ACTUAL INTERACTIVE CALENDAR GRID GENERATOR
// ==============================================
function renderFullCalendar() {
    renderCalendarMonthGrid();
    renderSelectedDaySchedule(calSelectedDateStr);
    renderAgendaList();
}

function renderCalendarMonthGrid() {
    if (!calGridCells) return;

    const monthNames = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ];

    calMonthYearTitle.innerText = `${monthNames[calCurrentMonth]} ${calCurrentYear}`;

    // Map events by date (YYYY-MM-DD)
    const eventsByDate = {};
    calendarEvents.forEach(ev => {
        const ymd = getEventYmd(ev);
        if (ymd) {
            if (!eventsByDate[ymd]) eventsByDate[ymd] = [];
            eventsByDate[ymd].push(ev);
        }
    });

    // Compute calendar cells
    const firstDayIndex = new Date(calCurrentYear, calCurrentMonth, 1).getDay(); // 0 = Sun
    const totalDaysInMonth = new Date(calCurrentYear, calCurrentMonth + 1, 0).getDate();
    const prevMonthDays = new Date(calCurrentYear, calCurrentMonth, 0).getDate();

    const todayStr = formatYmd(new Date());

    let cellsHtml = "";

    // 1. Previous Month Trailing Days
    for (let x = firstDayIndex - 1; x >= 0; x--) {
        const dayNum = prevMonthDays - x;
        const prevMonth = calCurrentMonth === 0 ? 11 : calCurrentMonth - 1;
        const prevYear = calCurrentMonth === 0 ? calCurrentYear - 1 : calCurrentYear;
        const ymd = `${prevYear}-${String(prevMonth + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
        
        cellsHtml += `
            <div class="cal-cell cal-cell-inactive" onclick="selectCalendarDate('${ymd}', ${prevYear}, ${prevMonth})">
                <span class="cal-day-num text-cream-700/50">${dayNum}</span>
            </div>
        `;
    }

    // 2. Current Month Days
    for (let day = 1; day <= totalDaysInMonth; day++) {
        const ymd = `${calCurrentYear}-${String(calCurrentMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
        const isToday = ymd === todayStr;
        const isSelected = ymd === calSelectedDateStr;
        const dayEvents = eventsByDate[ymd] || [];
        const hasEvents = dayEvents.length > 0;

        let cellClasses = "cal-cell";
        let priorityDotsHtml = "";

        if (hasEvents) {
            cellClasses += " cal-cell-has-events";
            const priorities = dayEvents.map(e => (e.priority || "medium").toLowerCase());
            const hasHigh = priorities.includes("high");
            const hasMed = priorities.includes("medium");
            const hasLow = priorities.includes("low");

            if (hasHigh) {
                cellClasses += " cal-cell-has-high";
            } else if (hasMed) {
                cellClasses += " cal-cell-has-medium";
            } else {
                cellClasses += " cal-cell-has-low";
            }

            // Priority dots in top corner
            priorityDotsHtml = `<div class="flex items-center gap-1">`;
            if (hasHigh) priorityDotsHtml += `<span class="w-1.5 h-1.5 rounded-full bg-[#D65538]" title="High priority event"></span>`;
            if (hasMed) priorityDotsHtml += `<span class="w-1.5 h-1.5 rounded-full bg-[#D99F26]" title="Medium priority event"></span>`;
            if (hasLow) priorityDotsHtml += `<span class="w-1.5 h-1.5 rounded-full bg-[#4E7857]" title="Low priority event"></span>`;
            priorityDotsHtml += `</div>`;
        }

        if (isSelected) cellClasses += " cal-cell-selected";

        // Generate chips for events in this day (colored by priority!)
        let eventChipsHtml = "";
        const maxDisplay = 2;
        dayEvents.slice(0, maxDisplay).forEach(ev => {
            const priority = (ev.priority || "medium").toLowerCase();
            const chipClass = priority === "high" ? "event-chip-high" : (priority === "low" ? "event-chip-low" : "event-chip-medium");
            const dotColor = priority === "high" ? "bg-[#D65538]" : (priority === "low" ? "bg-[#4E7857]" : "bg-[#D99F26]");

            eventChipsHtml += `
                <div class="event-chip ${chipClass}" title="${escapeHtml(ev.summary)} (${priority} priority)">
                    <span class="w-1.5 h-1.5 rounded-full ${dotColor} shrink-0"></span>
                    <span class="truncate">${escapeHtml(ev.summary || "Event")}</span>
                </div>
            `;
        });

        if (dayEvents.length > maxDisplay) {
            const remaining = dayEvents.length - maxDisplay;
            eventChipsHtml += `
                <div class="text-[9px] text-cream-700 font-bold px-1 text-center font-mono">
                    +${remaining} more
                </div>
            `;
        }

        cellsHtml += `
            <div class="${cellClasses}" onclick="selectCalendarDate('${ymd}', ${calCurrentYear}, ${calCurrentMonth})">
                <div class="flex items-center justify-between">
                    <span class="cal-day-num ${isToday ? 'cal-day-today' : ''}">${day}</span>
                    ${priorityDotsHtml}
                </div>
                <div class="flex flex-col gap-1 mt-1 overflow-hidden">
                    ${eventChipsHtml}
                </div>
            </div>
        `;
    }

    // 3. Next Month Leading Days to complete grid (total cells multiple of 7)
    const totalFilled = firstDayIndex + totalDaysInMonth;
    const remainingCells = (7 - (totalFilled % 7)) % 7;
    for (let d = 1; d <= remainingCells; d++) {
        const nextMonth = calCurrentMonth === 11 ? 0 : calCurrentMonth + 1;
        const nextYear = calCurrentMonth === 11 ? calCurrentYear + 1 : calCurrentYear;
        const ymd = `${nextYear}-${String(nextMonth + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

        cellsHtml += `
            <div class="cal-cell cal-cell-inactive" onclick="selectCalendarDate('${ymd}', ${nextYear}, ${nextMonth})">
                <span class="cal-day-num text-cream-700/50">${d}</span>
            </div>
        `;
    }

    calGridCells.innerHTML = cellsHtml;
}

window.selectCalendarDate = function(ymd, year, month) {
    calSelectedDateStr = ymd;
    if (year !== undefined && month !== undefined && (year !== calCurrentYear || month !== calCurrentMonth)) {
        calCurrentYear = year;
        calCurrentMonth = month;
    }
    renderCalendarMonthGrid();
    renderSelectedDaySchedule(ymd);
};

function renderSelectedDaySchedule(ymd) {
    if (!calSelectedDayHeading || !calSelectedDayEventsList) return;

    const dateObj = new Date(ymd + "T00:00:00");
    const options = { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' };
    const dateFormatted = dateObj.toLocaleDateString(undefined, options);

    calSelectedDayHeading.innerText = dateFormatted;

    // Filter events for this day
    const dayEvents = calendarEvents.filter(ev => {
        return getEventYmd(ev) === ymd;
    });

    if (dayEvents.length === 0) {
        calSelectedDayEventsList.innerHTML = `
            <div class="text-center py-10 px-4 bg-cream-50 rounded-2xl border border-cream-200 space-y-2">
                <i class="fa-regular fa-calendar-check text-2xl text-cream-300 block"></i>
                <p class="text-xs font-bold text-cream-900">No Events Scheduled</p>
                <p class="text-[11px] text-cream-700">Your schedule is free for this day.</p>
                <button onclick="openEventModal(null, '${ymd}')" class="mt-2 px-3 py-1.5 rounded-xl bg-sage-600 hover:bg-sage-700 text-white text-xs font-semibold shadow-xs transition inline-flex items-center gap-1.5">
                    <i class="fa-solid fa-plus text-[10px]"></i> Schedule Event
                </button>
            </div>
        `;
        return;
    }

    calSelectedDayEventsList.innerHTML = dayEvents.map(ev => {
        const startRaw = getEventStartRaw(ev);
        const endRaw = getEventEndRaw(ev);
        const timeFormatted = formatTimeString(startRaw, endRaw);
        const priority = (ev.priority || "medium").toLowerCase();

        let priorityPill = "";
        let cardAccent = "schedule-card-medium";
        if (priority === "high") {
            cardAccent = "schedule-card-high";
            priorityPill = `<span class="priority-pill-high px-2.5 py-0.5 rounded-full text-[10px] font-bold shrink-0">High Priority</span>`;
        } else if (priority === "low") {
            cardAccent = "schedule-card-low";
            priorityPill = `<span class="priority-pill-low px-2.5 py-0.5 rounded-full text-[10px] font-bold shrink-0">Low Priority</span>`;
        } else {
            cardAccent = "schedule-card-medium";
            priorityPill = `<span class="priority-pill-medium px-2.5 py-0.5 rounded-full text-[10px] font-bold shrink-0">Medium Priority</span>`;
        }

        return `
            <div class="card-aesthetic ${cardAccent} p-3.5 space-y-2">
                <div class="flex items-start justify-between gap-2">
                    <h4 class="text-xs font-bold text-cream-900 leading-snug">${escapeHtml(ev.summary || "Untitled Event")}</h4>
                    ${priorityPill}
                </div>

                <div class="flex flex-wrap items-center gap-2 text-[11px] text-cream-700 font-mono">
                    <span class="flex items-center gap-1 bg-cream-50 px-2 py-0.5 rounded border border-cream-200">
                        <i class="fa-regular fa-clock text-sage-600"></i> ${timeFormatted}
                    </span>
                    ${ev.location ? `<span class="flex items-center gap-1 text-cream-700 bg-cream-50 px-2 py-0.5 rounded border border-cream-200"><i class="fa-solid fa-location-dot text-sage-600"></i> ${escapeHtml(ev.location)}</span>` : ""}
                </div>

                ${ev.description ? `<p class="text-[11px] text-cream-700 leading-relaxed pt-0.5">${escapeHtml(ev.description)}</p>` : ""}

                <div class="flex items-center justify-between gap-1.5 pt-1.5 border-t border-cream-200">
                    <span class="flex items-center gap-1 text-[10px] text-cream-700 bg-cream-50 px-2 py-0.5 rounded border border-cream-200 font-mono">
                        <i class="fa-solid fa-user text-[9px] text-sage-600"></i>
                        <span>${escapeHtml(ev.user_id ? (ev.user_id.includes('@') ? ev.user_id.split('@')[0] : ev.user_id) : 'guest')}</span>
                    </span>
                    <div class="flex items-center gap-1.5">
                        <button onclick="editEvent('${ev.id}')" title="Edit Event" class="p-1.5 rounded-lg bg-cream-50 hover:bg-cream-100 border border-cream-200 text-cream-900 text-[11px] transition shadow-2xs">
                            <i class="fa-solid fa-pen text-sage-600"></i>
                        </button>
                        <button onclick="deleteEvent('${ev.id}')" title="Delete Event" class="p-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-[11px] transition shadow-2xs">
                            <i class="fa-solid fa-trash-can"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

// Agenda List View
function renderAgendaList() {
    if (!calendarEventsList) return;

    if (!calendarEvents || calendarEvents.length === 0) {
        calendarEventsList.innerHTML = `
            <div class="text-center py-16 text-cream-700 text-xs bg-white rounded-2xl border border-cream-200 shadow-2xs">
                <i class="fa-regular fa-calendar-xmark text-4xl mb-3 text-cream-300 block"></i>
                <p class="font-bold text-cream-900 text-sm mb-1">No Events Found</p>
                <p>You have no scheduled appointments yet. Click "+ Create Event" to add one!</p>
            </div>
        `;
        return;
    }

    calendarEventsList.innerHTML = calendarEvents.map(ev => {
        const startRaw = getEventStartRaw(ev);
        const endRaw = getEventEndRaw(ev);
        const dateObj = startRaw ? new Date(startRaw) : new Date();
        const monthShort = dateObj.toLocaleDateString(undefined, { month: 'short' });
        const dayNum = dateObj.getDate();
        const formattedDate = formatDateString(startRaw);
        const formattedTime = formatTimeString(startRaw, endRaw);
        const priority = (ev.priority || "medium").toLowerCase();

        let priorityPill = "";
        let cardAccent = "schedule-card-medium";
        let dateBadgeClass = "bg-sage-50 border-sage-200";
        let monthColor = "text-sage-700";

        if (priority === "high") {
            cardAccent = "schedule-card-high";
            priorityPill = `<span class="priority-pill-high px-2.5 py-0.5 rounded-full text-[10px] font-bold">High Priority</span>`;
            dateBadgeClass = "bg-[#FDF4F1] border-[#F2D5CD]";
            monthColor = "text-[#963826]";
        } else if (priority === "low") {
            cardAccent = "schedule-card-low";
            priorityPill = `<span class="priority-pill-low px-2.5 py-0.5 rounded-full text-[10px] font-bold">Low Priority</span>`;
            dateBadgeClass = "bg-[#EDF5EE] border-[#C8E0CB]";
            monthColor = "text-[#284E33]";
        } else {
            cardAccent = "schedule-card-medium";
            priorityPill = `<span class="priority-pill-medium px-2.5 py-0.5 rounded-full text-[10px] font-bold">Medium Priority</span>`;
            dateBadgeClass = "bg-[#FAF5E8] border-[#EEDEB8]";
            monthColor = "text-[#7C5914]";
        }

        return `
            <div class="card-aesthetic ${cardAccent} p-5 flex items-start justify-between gap-4">
                <div class="flex items-start gap-4 flex-1">
                    <div class="date-badge ${dateBadgeClass}">
                        <span class="date-badge-month ${monthColor}">${monthShort}</span>
                        <span class="date-badge-day">${dayNum}</span>
                    </div>

                    <div class="space-y-1.5 flex-1">
                        <div class="flex items-center gap-2.5">
                            <h3 class="text-sm font-bold text-cream-900">${escapeHtml(ev.summary || "Untitled Event")}</h3>
                            ${priorityPill}
                            <span class="text-[10px] bg-cream-50 text-cream-700 border border-cream-200 px-2 py-0.5 rounded font-mono flex items-center gap-1">
                                <i class="fa-solid fa-user text-[9px] text-sage-600"></i> ${escapeHtml(ev.user_id ? (ev.user_id.includes('@') ? ev.user_id.split('@')[0] : ev.user_id) : 'guest')}
                            </span>
                        </div>
                        
                        <div class="flex flex-wrap items-center gap-3 text-xs text-cream-700 font-mono">
                            <span class="flex items-center gap-1.5 bg-cream-50 px-2 py-0.5 rounded-md border border-cream-200">
                                <i class="fa-regular fa-calendar text-sage-600"></i> ${formattedDate}
                            </span>
                            <span class="flex items-center gap-1.5 bg-cream-50 px-2 py-0.5 rounded-md border border-cream-200">
                                <i class="fa-regular fa-clock text-sage-600"></i> ${formattedTime}
                            </span>
                            ${ev.location ? `
                                <span class="flex items-center gap-1.5 text-cream-700">
                                    <i class="fa-solid fa-location-dot text-sage-600"></i> ${escapeHtml(ev.location)}
                                </span>` : ""
                            }
                        </div>

                        ${ev.description ? `
                            <p class="text-xs text-cream-700 leading-relaxed pt-1">${escapeHtml(ev.description)}</p>
                        ` : ""}
                    </div>
                </div>

                <div class="flex items-center gap-1.5 shrink-0">
                    <button onclick="editEvent('${ev.id}')" title="Edit Event" class="p-2 rounded-xl bg-white border border-cream-200 hover:bg-cream-100 text-cream-900 transition text-xs shadow-2xs">
                        <i class="fa-solid fa-pen text-sage-600"></i>
                    </button>
                    <button onclick="deleteEvent('${ev.id}')" title="Delete Event" class="p-2 rounded-xl bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 transition text-xs shadow-2xs">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

// Load BERT Hashed DB
async function loadHashedTable() {
    if (!hashedTableFullContainer) return;
    try {
        const res = await authFetch("/api/embeddings/table");
        const data = await res.json();
        hashedRecords = data.records || [];
        renderHashedTable();
    } catch (e) {
        if (hashedTableFullContainer) {
            hashedTableFullContainer.innerHTML = `<p class="text-rose-600 text-xs">Error loading hashed database.</p>`;
        }
    }
}

// Render engraved welcome screen
function renderWelcomeScreen() {
    if (!chatMessages) return;
    let rawName = currentUserName || (currentUserEmail ? currentUserEmail.split("@")[0] : "Guest");
    let formattedName = rawName ? (rawName.charAt(0).toUpperCase() + rawName.slice(1)) : "Guest";
    chatMessages.innerHTML = `
        <div id="chatWelcomeScreen" class="engraved-welcome-container">
            <div class="engraved-welcome-icon">
                <i class="fa-solid fa-leaf"></i>
            </div>
            <h1 class="engraved-welcome-text">
                Welcome, <span id="welcomeUserName">${escapeHtml(formattedName)}</span>
            </h1>
            <p class="engraved-welcome-subtext">Intelligent Calendar Assistant</p>
            <div class="engraved-welcome-ornament">
                <span class="ornament-line"></span>
                <i class="fa-solid fa-feather text-[10px] text-cream-600 opacity-60"></i>
                <span class="ornament-line"></span>
            </div>
        </div>
    `;
}

// Load Chat History for Multi-User Persistence
async function loadChatHistory() {
    try {
        const res = await authFetch("/api/chat/history");
        const data = await res.json();
        const messages = data.messages || [];
        if (!chatMessages) return;

        if (messages.length === 0) {
            renderWelcomeScreen();
            return;
        }

        // Clear welcome screen / previous messages and render chat history
        chatMessages.innerHTML = "";
        messages.forEach(msg => {
            if (msg.sender === "user") {
                appendUserMessage(msg.message);
            } else {
                appendAiMessage({
                    response: msg.message,
                    ai_powered: true,
                    ai_provider: "Groq",
                    executed_action: msg.metadata?.executed_action
                });
            }
        });
    } catch (e) {
        console.warn("loadChatHistory notice:", e);
    }
}

function renderHashedTable() {
    if (!hashedRecords || hashedRecords.length === 0) {
        hashedTableFullContainer.innerHTML = `<div class="text-center py-10 text-cream-700 text-xs bg-white rounded-2xl border border-cream-200">Table is empty. Sync to populate!</div>`;
        return;
    }

    hashedTableFullContainer.innerHTML = hashedRecords.map((rec, idx) => {
        const preview = rec.vector_preview ? rec.vector_preview.join(", ") : "";
        const eventPriority = rec.event?.priority || "medium";
        const priorityBadge = eventPriority === "high" 
            ? `<span class="priority-pill-high px-2.5 py-0.5 rounded-full text-[10px] font-bold">High Priority</span>`
            : (eventPriority === "low" 
                ? `<span class="priority-pill-low px-2.5 py-0.5 rounded-full text-[10px] font-bold">Low Priority</span>`
                : `<span class="priority-pill-medium px-2.5 py-0.5 rounded-full text-[10px] font-bold">Medium Priority</span>`);

        return `
            <div class="card-aesthetic p-5 font-mono text-xs space-y-3">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <span class="text-cream-700/60 font-semibold">#${idx + 1}</span>
                        <span class="text-cream-900 font-bold text-sm">${escapeHtml(rec.summary)}</span>
                        ${priorityBadge}
                    </div>
                    <span class="px-2.5 py-0.5 rounded-full bg-sage-100 text-sage-800 border border-sage-200 text-[11px] font-semibold">
                        Dim: ${rec.dimension} (BERT Pooled)
                    </span>
                </div>

                <div class="flex items-center gap-2 text-[11px]">
                    <span class="text-cream-700 font-sans font-medium">64-bit Semantic Hash:</span>
                    <span class="text-sage-800 font-bold bg-sage-50 px-2 py-0.5 rounded border border-sage-200">
                        ${rec.semantic_hash}
                    </span>
                </div>

                <div class="text-cream-900 text-[11px] truncate bg-cream-50 p-2.5 rounded-xl border border-cream-200">
                    <span class="text-cream-700 font-sans font-medium">Raw Representation:</span> ${escapeHtml(rec.raw_text)}
                </div>

                <div class="text-cream-700 text-[10px] truncate" title="${preview}">
                    <span class="font-sans font-medium">Vector weights:</span> [${preview}...]
                </div>
            </div>
        `;
    }).join("");
}

// Chat Functionality
function setupChat() {
    chatForm.addEventListener("submit", handleChatSubmit);

    // Clear Chat Button
    if (btnClearChat) {
        btnClearChat.addEventListener("click", async () => {
            if (!confirm("Are you sure you want to clear your chat history?")) return;
            try {
                await authFetch("/api/chat/history", { method: "DELETE" });
                loadChatHistory();
                showToast("Chat history cleared.");
            } catch (err) {
                alert("Failed to clear chat: " + err.message);
            }
        });
    }

    // Quick prompts
    document.querySelectorAll(".quick-prompt").forEach(btn => {
        btn.addEventListener("click", () => {
            chatInput.value = btn.innerText.trim();
            chatForm.dispatchEvent(new Event("submit"));
        });
    });

    if (btnSidebarSync) {
        btnSidebarSync.addEventListener("click", async () => {
            btnSidebarSync.classList.add("opacity-50");
            try {
                const res = await authFetch("/api/calendar/sync", { method: "POST" });
                const data = await res.json();
                await loadCalendarEvents();
                await loadHashedTable();
                showToast(`Synchronized ${data.total_indexed} events with BERT Hashed DB!`);
            } catch (e) {
                console.error(e);
            } finally {
                btnSidebarSync.classList.remove("opacity-50");
            }
        });
    }

    if (btnRefreshHashedDB) {
        btnRefreshHashedDB.addEventListener("click", () => loadHashedTable());
    }
}

// Speech Recognition (Web Speech API + Groq Whisper Fallback)
function setupSpeechRecognition() {
    const btnVoiceInput = document.getElementById("btnVoiceInput");
    const voiceInputIcon = document.getElementById("voiceInputIcon");
    const voiceStatusContainer = document.getElementById("voiceStatusContainer");
    const voiceStatusText = document.getElementById("voiceStatusText");
    const btnCancelVoice = document.getElementById("btnCancelVoice");

    if (!btnVoiceInput) return;

    let isRecording = false;
    let recognition = null;
    let mediaRecorder = null;
    let audioChunks = [];

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    function setRecordingUI(active, statusText = "Listening to your voice... Speak your calendar query now") {
        isRecording = active;
        if (active) {
            btnVoiceInput.className = "w-11 h-11 rounded-2xl bg-rose-500 hover:bg-rose-600 text-white border border-rose-400 flex items-center justify-center transition shadow-md shrink-0 animate-pulse";
            if (voiceInputIcon) voiceInputIcon.className = "fa-solid fa-microphone-lines text-sm";
            if (voiceStatusContainer) {
                voiceStatusContainer.classList.remove("hidden");
                if (voiceStatusText) voiceStatusText.innerText = statusText;
            }
            chatInput.placeholder = "Listening... Speak your request now...";
        } else {
            btnVoiceInput.className = "w-11 h-11 rounded-2xl bg-cream-100 hover:bg-cream-200 text-cream-700 hover:text-sage-700 border border-cream-200 flex items-center justify-center transition shadow-2xs shrink-0 active:scale-95";
            if (voiceInputIcon) voiceInputIcon.className = "fa-solid fa-microphone text-sm";
            if (voiceStatusContainer) {
                voiceStatusContainer.classList.add("hidden");
            }
            chatInput.placeholder = "Ask about your calendar, schedule an event, or chat freely...";
            chatInput.focus();
        }
    }

    function stopRecording() {
        if (!isRecording) return;
        if (recognition) {
            try { recognition.stop(); } catch (e) {}
        }
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            try { mediaRecorder.stop(); } catch (e) {}
        }
        setRecordingUI(false);
    }

    if (btnCancelVoice) {
        btnCancelVoice.addEventListener("click", () => {
            stopRecording();
            showToast("Voice recognition cancelled.");
        });
    }

    // 1. Primary: Native Browser Web Speech API
    if (SpeechRecognition) {
        try {
            recognition = new SpeechRecognition();
            recognition.continuous = false;
            recognition.interimResults = true;
            recognition.lang = navigator.language || "en-US";

            recognition.onstart = () => {
                setRecordingUI(true, "Listening... Speak your calendar query now");
            };

            recognition.onresult = (event) => {
                let interimTranscript = "";
                let finalTranscript = "";

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                const currentText = finalTranscript || interimTranscript;
                if (currentText) {
                    chatInput.value = currentText;
                }
            };

            recognition.onerror = (event) => {
                console.warn("Speech recognition error:", event.error);
                setRecordingUI(false);
                if (event.error === "not-allowed" || event.error === "service-not-allowed") {
                    showToast("Microphone access denied. Please allow microphone permissions in browser.");
                } else if (event.error !== "no-speech") {
                    showToast("Speech recognition notice: " + event.error);
                }
            };

            recognition.onend = () => {
                setRecordingUI(false);
                if (chatInput.value.trim()) {
                    showToast("Speech recognized! Click Send or press Enter.");
                }
            };

            btnVoiceInput.addEventListener("click", () => {
                if (isRecording) {
                    recognition.stop();
                    setRecordingUI(false);
                } else {
                    try {
                        recognition.start();
                    } catch (err) {
                        console.warn("SpeechRecognition start error:", err);
                        recognition.stop();
                        setRecordingUI(false);
                    }
                }
            });

            return; // Web Speech API successfully set up
        } catch (e) {
            console.warn("Falling back to MediaRecorder Whisper speech recognition:", e);
        }
    }

    // 2. Fallback: MediaRecorder + Groq Whisper API
    btnVoiceInput.addEventListener("click", async () => {
        if (isRecording) {
            stopRecording();
            return;
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            alert("Microphone access is not supported in this browser.");
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunks = [];
            mediaRecorder = new MediaRecorder(stream);

            mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.push(e.data);
            };

            mediaRecorder.onstop = async () => {
                stream.getTracks().forEach(track => track.stop());
                setRecordingUI(false);

                if (audioChunks.length === 0) return;
                const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                const formData = new FormData();
                formData.append("file", audioBlob, "speech.webm");

                if (voiceStatusContainer) {
                    voiceStatusContainer.classList.remove("hidden");
                    if (voiceStatusText) voiceStatusText.innerText = "Transcribing with Whisper AI...";
                }

                try {
                    const res = await authFetch("/api/audio/transcribe", {
                        method: "POST",
                        body: formData
                    });
                    const data = await res.json();
                    if (data.text) {
                        chatInput.value = data.text;
                        showToast("Voice transcribed with Whisper AI!");
                        chatInput.focus();
                    } else if (data.detail) {
                        showToast("Transcription notice: " + data.detail);
                    }
                } catch (err) {
                    console.error("Audio transcribe error:", err);
                    showToast("Transcription failed: " + err.message);
                } finally {
                    if (voiceStatusContainer) voiceStatusContainer.classList.add("hidden");
                }
            };

            mediaRecorder.start();
            setRecordingUI(true, "Recording audio (Whisper AI)... Click mic to finish");
        } catch (err) {
            console.error("Microphone access error:", err);
            setRecordingUI(false);
            if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
                showToast("Microphone permission was denied. Please allow microphone in browser.");
            } else {
                showToast("Microphone error: " + err.message);
            }
        }
    });
}

async function handleChatSubmit(e) {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    appendUserMessage(query);
    chatInput.value = "";
    btnSendChat.disabled = true;

    const typingId = appendTypingIndicator();

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 60000);

        const res = await authFetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: query, top_k: 4 }),
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        const data = await res.json();
        removeMessage(typingId);

        appendAiMessage(data);

        if (data.executed_action) {
            await loadCalendarEvents();
            await loadHashedTable();
        }
    } catch (err) {
        removeMessage(typingId);
        appendErrorMessage("Request failed: " + err.message);
    } finally {
        btnSendChat.disabled = false;
        chatInput.focus();
    }
}

function clearWelcomeScreenIfNeeded() {
    const welcomeScreen = document.getElementById("chatWelcomeScreen");
    if (welcomeScreen) {
        welcomeScreen.remove();
    }
}

function appendUserMessage(text) {
    clearWelcomeScreenIfNeeded();
    const div = document.createElement("div");
    div.className = "flex justify-end";
    div.innerHTML = `
        <div class="bg-sage-600 text-white rounded-2xl rounded-tr-xs px-5 py-3 max-w-lg text-sm shadow-2xs leading-relaxed font-normal">
            ${escapeHtml(text)}
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendAiMessage(data) {
    clearWelcomeScreenIfNeeded();
    const div = document.createElement("div");
    div.className = "flex items-start gap-3.5";

    const providerIcon = data.ai_provider === "Groq" ? "fa-bolt text-sage-600" : "fa-leaf text-sage-600";
    const providerName = data.ai_provider || "Groq";

    const modeBadge = data.is_calendar_task ? `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sage-100 text-sage-800 border border-sage-200">
            <i class="fa-solid fa-database text-sage-600"></i> BERT RAG Task
        </span>
    ` : `
        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-cream-100 text-cream-900 border border-cream-200">
            <i class="fa-regular fa-comments text-sage-600"></i> Regular Chat
        </span>
    `;

    const aiBadge = data.ai_powered ? `
        <div class="mb-2 flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-sage-50 text-sage-800 border border-sage-200 shadow-2xs">
                <i class="fa-solid ${providerIcon}"></i>
                ${escapeHtml(providerName)} (${escapeHtml(data.ai_model || 'Fast')})
            </span>
            ${modeBadge}
        </div>
    ` : `
        <div class="mb-2 flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-medium bg-cream-100 text-cream-700 border border-cream-200">
                <i class="fa-solid fa-microchip"></i> Local Engine
            </span>
            ${modeBadge}
        </div>
    `;

    // Action banner with Priority if available
    let actionBadge = "";
    if (data.executed_action) {
        const ev = data.executed_action.event;
        let priPill = "";
        if (ev && ev.priority) {
            const p = ev.priority.toLowerCase();
            if (p === "high") priPill = `<span class="priority-pill-high px-2 py-0.5 rounded-full text-[10px] font-bold">High Priority</span>`;
            else if (p === "low") priPill = `<span class="priority-pill-low px-2 py-0.5 rounded-full text-[10px] font-bold">Low Priority</span>`;
            else priPill = `<span class="priority-pill-medium px-2 py-0.5 rounded-full text-[10px] font-bold">Medium Priority</span>`;
        }

        if (data.executed_action.type === "CREATED") {
            const sum = ev?.summary || data.executed_action.summary || "New Event";
            actionBadge = `
                <div class="mt-2.5 px-3.5 py-2.5 rounded-xl bg-sage-50 border border-sage-200 text-sage-800 text-xs flex items-center justify-between gap-2 font-medium">
                    <div class="flex items-center gap-2">
                        <i class="fa-solid fa-circle-check text-sage-600"></i>
                        <span><b>Event Scheduled:</b> ${escapeHtml(sum)}</span>
                    </div>
                    ${priPill}
                </div>
            `;
        } else if (data.executed_action.type === "UPDATED") {
            const sum = ev?.summary || data.executed_action.summary || "Event";
            actionBadge = `
                <div class="mt-2.5 px-3.5 py-2.5 rounded-xl bg-[#FAF5E8] border border-[#EEDEB8] text-[#7C5914] text-xs flex items-center justify-between gap-2 font-medium">
                    <div class="flex items-center gap-2">
                        <i class="fa-solid fa-calendar-check text-[#D99F26]"></i>
                        <span><b>Event Updated:</b> ${escapeHtml(sum)}</span>
                    </div>
                    ${priPill}
                </div>
            `;
        } else if (data.executed_action.type === "DELETED") {
            const delSummary = data.executed_action.summary || ev?.summary || "Event";
            actionBadge = `
                <div class="mt-2.5 px-3.5 py-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center justify-between gap-2 font-medium">
                    <div class="flex items-center gap-2">
                        <i class="fa-solid fa-trash-can text-rose-600"></i>
                        <span><b>Event Cancelled:</b> ${escapeHtml(delSummary)}</span>
                    </div>
                    <span class="text-[10px] bg-rose-100 text-rose-800 px-2 py-0.5 rounded-full font-bold">Deleted</span>
                </div>
            `;
        }
    }

    const matchesHtml = (data.retrieved_matches || []).map((m, idx) => `
        <div class="flex items-center justify-between text-[11px] p-2 rounded-xl bg-cream-50 border border-cream-200 mb-1 font-mono">
            <span class="text-cream-900 font-medium truncate max-w-[240px]">#${idx + 1} ${escapeHtml(m.summary)}</span>
            <div class="flex items-center gap-2 shrink-0">
                <span class="text-sage-700 font-bold">sim: ${m.similarity_score.toFixed(3)}</span>
                <span class="text-cream-700 bg-white px-1.5 py-0.5 rounded border border-cream-200">${m.semantic_hash.substring(0, 6)}..</span>
            </div>
        </div>
    `).join("");

    const cosineAccordion = (data.retrieved_matches && data.retrieved_matches.length > 0) ? `
        <details class="text-xs bg-cream-50 border border-cream-200 rounded-xl p-3 mt-3">
            <summary class="cursor-pointer text-sage-700 font-semibold hover:text-sage-800 flex items-center justify-between select-none">
                <span class="flex items-center gap-1.5">
                    <i class="fa-solid fa-network-wired text-sage-600"></i>
                    BERT Cosine Similarity Matches (${data.retrieved_matches.length})
                </span>
                <i class="fa-solid fa-chevron-down text-[10px]"></i>
            </summary>
            <div class="mt-2.5 pt-2 border-t border-cream-200 space-y-2">
                ${matchesHtml}
                ${data.reasoning ? `
                    <div class="mt-2 p-2.5 rounded-lg bg-white border border-cream-200 text-cream-700 text-[11px] leading-relaxed">
                        <b class="text-cream-900 font-semibold">Reasoning:</b> ${escapeHtml(data.reasoning)}
                    </div>
                ` : ""}
            </div>
        </details>
    ` : "";

    div.innerHTML = `
        <div class="w-8 h-8 rounded-xl bg-sage-600 text-white flex items-center justify-center shrink-0 shadow-2xs">
            <i class="fa-solid fa-leaf text-xs"></i>
        </div>
        <div class="card-aesthetic rounded-tl-xs p-5 max-w-2xl text-sm leading-relaxed text-cream-900 space-y-3">
            ${aiBadge}
            <div class="leading-relaxed">${formatMarkdown(data.response)}</div>
            ${actionBadge}
            ${cosineAccordion}
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function appendTypingIndicator() {
    clearWelcomeScreenIfNeeded();
    const id = "typing-" + Date.now();
    const div = document.createElement("div");
    div.id = id;
    div.className = "flex items-start gap-3.5";
    div.innerHTML = `
        <div class="w-8 h-8 rounded-xl bg-white border border-cream-200 flex items-center justify-center shrink-0 shadow-2xs">
            <i class="fa-solid fa-spinner fa-spin text-sage-600 text-xs"></i>
        </div>
        <div class="bg-white border border-cream-200 rounded-2xl px-4 py-3 text-xs text-cream-700 flex items-center gap-2 shadow-2xs">
            <span>Thinking</span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return id;
}

function removeMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function appendErrorMessage(msg) {
    clearWelcomeScreenIfNeeded();
    const div = document.createElement("div");
    div.className = "flex items-start gap-3";
    div.innerHTML = `
        <div class="w-8 h-8 rounded-xl bg-rose-50 border border-rose-200 flex items-center justify-center shrink-0">
            <i class="fa-solid fa-circle-exclamation text-rose-600 text-xs"></i>
        </div>
        <div class="bg-rose-50 border border-rose-200 rounded-2xl p-3 text-xs text-rose-800 font-medium">
            ${escapeHtml(msg)}
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Calendar Navigation & Handlers
function setupCalendarHandlers() {
    // Month navigation
    if (btnPrevMonth) {
        btnPrevMonth.addEventListener("click", () => {
            calCurrentMonth--;
            if (calCurrentMonth < 0) {
                calCurrentMonth = 11;
                calCurrentYear--;
            }
            renderCalendarMonthGrid();
        });
    }

    if (btnNextMonth) {
        btnNextMonth.addEventListener("click", () => {
            calCurrentMonth++;
            if (calCurrentMonth > 11) {
                calCurrentMonth = 0;
                calCurrentYear++;
            }
            renderCalendarMonthGrid();
        });
    }

    if (btnToday) {
        btnToday.addEventListener("click", () => {
            const now = new Date();
            calCurrentYear = now.getFullYear();
            calCurrentMonth = now.getMonth();
            calSelectedDateStr = formatYmd(now);
            renderCalendarMonthGrid();
            renderSelectedDaySchedule(calSelectedDateStr);
        });
    }

    // Toggle Grid vs Agenda
    if (btnToggleGridView && btnToggleListView) {
        btnToggleGridView.addEventListener("click", () => {
            calViewMode = "grid";
            calGridSection.classList.remove("hidden");
            calAgendaSection.classList.add("hidden");
            btnToggleGridView.classList.add("bg-white", "text-sage-800", "font-bold", "shadow-2xs", "border", "border-cream-200");
            btnToggleGridView.classList.remove("text-cream-700", "font-medium");
            btnToggleListView.classList.remove("bg-white", "text-sage-800", "font-bold", "shadow-2xs", "border", "border-cream-200");
            btnToggleListView.classList.add("text-cream-700", "font-medium");
            renderCalendarMonthGrid();
        });

        btnToggleListView.addEventListener("click", () => {
            calViewMode = "agenda";
            calGridSection.classList.add("hidden");
            calAgendaSection.classList.remove("hidden");
            btnToggleListView.classList.add("bg-white", "text-sage-800", "font-bold", "shadow-2xs", "border", "border-cream-200");
            btnToggleListView.classList.remove("text-cream-700", "font-medium");
            btnToggleGridView.classList.remove("bg-white", "text-sage-800", "font-bold", "shadow-2xs", "border", "border-cream-200");
            btnToggleGridView.classList.add("text-cream-700", "font-medium");
            renderAgendaList();
        });
    }

    if (btnAddEventForSelectedDay) {
        btnAddEventForSelectedDay.addEventListener("click", () => {
            openEventModal(null, calSelectedDateStr);
        });
    }

    if (btnOpenCreateEvent) {
        btnOpenCreateEvent.addEventListener("click", (e) => {
            e.preventDefault();
            openEventModal(null, calSelectedDateStr);
        });
    }
    if (btnCloseModal) {
        btnCloseModal.addEventListener("click", closeEventModal);
    }
    if (btnCancelModal) {
        btnCancelModal.addEventListener("click", closeEventModal);
    }
    if (eventForm) {
        eventForm.addEventListener("submit", handleSaveEvent);
    }
}

function closeEventModal() {
    if (eventModal) {
        eventModal.classList.add("hidden");
        eventModal.style.display = "none";
    }
}
window.closeEventModal = closeEventModal;

function openEventModal(event = null, prefillDateStr = null) {
    if (eventForm) eventForm.reset();
    if (modalOptionalDetails) {
        modalOptionalDetails.open = false; // Collapsed by default for new events
    }
    if (event) {
        if (modalTitle) modalTitle.innerHTML = `<i class="fa-solid fa-pen text-sage-600"></i> Edit Calendar Event`;
        if (modalEventId) modalEventId.value = event.id || "";
        if (modalSummary) modalSummary.value = event.summary || "";
        if (modalLocation) modalLocation.value = event.location || "";
        if (modalDescription) modalDescription.value = event.description || "";
        if (modalPriority) modalPriority.value = (event.priority || "medium").toLowerCase();
        
        const startRaw = event.start?.dateTime || event.start?.date || event.date_time || event.start_time || "";

        if (startRaw) {
            if (modalEventDate) modalEventDate.value = startRaw.substring(0, 10);
            if (startRaw.includes("T") && !startRaw.includes("T00:00:00")) {
                const timeStr = startRaw.substring(11, 16);
                if (modalEventTime) modalEventTime.value = timeStr;
                if (modalStartTime) modalStartTime.value = timeStr;
                if (modalOptionalDetails) modalOptionalDetails.open = true;
            } else {
                if (modalEventTime) modalEventTime.value = "";
                if (modalStartTime) modalStartTime.value = "";
            }
        } else {
            if (modalEventDate) modalEventDate.value = "";
            if (modalEventTime) modalEventTime.value = "";
            if (modalStartTime) modalStartTime.value = "";
        }
        if (event.location || event.description || (event.priority && event.priority !== "medium")) {
            if (modalOptionalDetails) modalOptionalDetails.open = true;
        }
    } else {
        if (modalTitle) modalTitle.innerHTML = `<i class="fa-solid fa-calendar-plus text-sage-600"></i> Create New Calendar Event`;
        if (modalEventId) modalEventId.value = "";
        if (modalSummary) modalSummary.value = "";
        if (modalLocation) modalLocation.value = "";
        if (modalDescription) modalDescription.value = "";
        if (modalPriority) modalPriority.value = "medium";
        if (modalEventTime) modalEventTime.value = "";
        if (modalStartTime) modalStartTime.value = "";
        if (modalEndTime) modalEndTime.value = "";
        
        let dStr = prefillDateStr || calSelectedDateStr;
        if (!dStr) {
            const d = new Date();
            d.setDate(d.getDate() + 1); // Tomorrow
            dStr = d.toISOString().substring(0, 10);
        }
        if (modalEventDate) modalEventDate.value = dStr;
    }
    const modalUserIndicator = document.getElementById("modalUserIndicator");
    if (modalUserIndicator) {
        modalUserIndicator.innerText = currentUserEmail || "Guest";
    }
    if (eventModal) {
        eventModal.classList.remove("hidden");
        eventModal.style.display = "flex";
    }
}
window.openEventModal = openEventModal;

async function handleSaveEvent(e) {
    e.preventDefault();
    const eventId = modalEventId ? modalEventId.value : "";
    const summaryVal = modalSummary ? modalSummary.value.trim() : "";
    const dateVal = modalEventDate ? modalEventDate.value : ""; // YYYY-MM-DD (mandatory)

    if (!summaryVal || !dateVal) {
        alert("Please provide both Event Name and Event Date.");
        return;
    }

    const priorityVal = modalPriority ? modalPriority.value : "medium";
    const timeInput = modalEventTime || modalStartTime;
    const timeVal = timeInput ? timeInput.value.trim() : ""; // optional HH:MM

    let dateTimeVal = dateVal;
    if (timeVal) {
        dateTimeVal = `${dateVal}T${timeVal}:00`;
    }

    const payload = {
        summary: summaryVal,
        date_time: dateTimeVal,
        event_date: dateVal,
        start_time: dateTimeVal,
        end_time: dateTimeVal,
        priority: priorityVal,
        location: modalLocation ? modalLocation.value.trim() : "",
        description: modalDescription ? modalDescription.value.trim() : "",
        user_id: currentUserEmail || currentUserId || "guest"
    };

    const submitBtn = document.getElementById("btnSaveEventModal");
    const originalText = submitBtn ? submitBtn.innerHTML : "";
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-xs"></i> <span>Saving...</span>`;
    }

    try {
        let res;
        if (eventId) {
            res = await authFetch(`/api/calendar/events/${eventId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        } else {
            res = await authFetch("/api/calendar/events", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
        }
        
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `Server error (HTTP ${res.status})`);
        }
        
        await res.json();
        closeEventModal();
        showToast(eventId ? "Event updated and re-hashed!" : "New event created and hashed with BERT!");
        await loadCalendarEvents();
        await loadHashedTable();
    } catch (err) {
        console.error("Save event error:", err);
        alert("Failed to save event: " + err.message);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    }
}

window.editEvent = function(id) {
    const ev = calendarEvents.find(e => e.id === id);
    if (ev) openEventModal(ev);
};

window.deleteEvent = async function(id) {
    if (!confirm("Are you sure you want to delete this event?")) return;
    try {
        await authFetch(`/api/calendar/events/${id}`, { method: "DELETE" });
        showToast("Event deleted from calendar and hashed database.");
        await loadCalendarEvents();
        await loadHashedTable();
    } catch (err) {
        alert("Failed to delete event: " + err.message);
    }
};

// Google OAuth & Settings Handlers
function setupGoogleAuthHandlers() {
    const accountModal = document.getElementById("accountModal");
    const btnCloseAccountModal = document.getElementById("btnCloseAccountModal");
    const btnGoogleSignInModal = document.getElementById("btnGoogleSignInModal");

    // Trigger Google Sign-In with Calendar Scopes directly
    if (btnGoogleSignInMain) {
        btnGoogleSignInMain.addEventListener("click", () => {
            startGoogleCalendarOAuth();
        });
    }

    if (btnCloseAccountModal && accountModal) {
        btnCloseAccountModal.addEventListener("click", () => {
            accountModal.classList.add("hidden");
        });
    }

    // Google Sign-In button inside Modal
    if (btnGoogleSignInModal) {
        btnGoogleSignInModal.addEventListener("click", () => {
            startGoogleCalendarOAuth();
        });
    }

    // Auth Modal Elements
    const tabBtnLogin = document.getElementById("tabBtnLogin");
    const tabBtnRegister = document.getElementById("tabBtnRegister");
    const authFieldFullName = document.getElementById("authFieldFullName");
    const passwordHint = document.getElementById("passwordHint");
    const passwordAuthForm = document.getElementById("passwordAuthForm");
    const inputAuthFullName = document.getElementById("inputAuthFullName");
    const inputAuthEmail = document.getElementById("inputAuthEmail");
    const inputAuthPassword = document.getElementById("inputAuthPassword");
    const btnSubmitAuth = document.getElementById("btnSubmitAuth");
    const btnSubmitAuthText = document.getElementById("btnSubmitAuthText");
    const authErrorBanner = document.getElementById("authErrorBanner");
    const authErrorMessage = document.getElementById("authErrorMessage");
    const btnTogglePasswordVisibility = document.getElementById("btnTogglePasswordVisibility");

    let authMode = "login"; // "login" or "register"

    function setAuthMode(mode) {
        authMode = mode;
        if (authErrorBanner) authErrorBanner.classList.add("hidden");
        if (mode === "login") {
            if (tabBtnLogin) tabBtnLogin.className = "flex-1 py-1.5 text-xs font-bold rounded-lg bg-white text-cream-900 shadow-2xs transition";
            if (tabBtnRegister) tabBtnRegister.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg text-cream-700 hover:text-cream-900 transition";
            if (authFieldFullName) authFieldFullName.classList.add("hidden");
            if (passwordHint) passwordHint.classList.add("hidden");
            if (btnSubmitAuthText) btnSubmitAuthText.innerText = "Log In to Workspace";
        } else {
            if (tabBtnRegister) tabBtnRegister.className = "flex-1 py-1.5 text-xs font-bold rounded-lg bg-white text-cream-900 shadow-2xs transition";
            if (tabBtnLogin) tabBtnLogin.className = "flex-1 py-1.5 text-xs font-semibold rounded-lg text-cream-700 hover:text-cream-900 transition";
            if (authFieldFullName) authFieldFullName.classList.remove("hidden");
            if (passwordHint) passwordHint.classList.remove("hidden");
            if (btnSubmitAuthText) btnSubmitAuthText.innerText = "Create Account & Sign In";
        }
    }

    if (tabBtnLogin) tabBtnLogin.addEventListener("click", () => setAuthMode("login"));
    if (tabBtnRegister) tabBtnRegister.addEventListener("click", () => setAuthMode("register"));

    if (btnTogglePasswordVisibility && inputAuthPassword) {
        btnTogglePasswordVisibility.addEventListener("click", () => {
            const isPassword = inputAuthPassword.type === "password";
            inputAuthPassword.type = isPassword ? "text" : "password";
            btnTogglePasswordVisibility.innerHTML = isPassword ? `<i class="fa-regular fa-eye-slash"></i>` : `<i class="fa-regular fa-eye"></i>`;
        });
    }

    function showAuthError(msg) {
        if (authErrorBanner && authErrorMessage) {
            const m = msg.toLowerCase();
            if (m.includes("already") && m.includes("registered")) {
                authErrorMessage.innerHTML = `${escapeHtml(msg)}. <a href="#" id="linkSwitchToLogin" class="underline font-bold text-rose-800 ml-1">Switch to Log In →</a>`;
                const link = document.getElementById("linkSwitchToLogin");
                if (link) {
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        setAuthMode("login");
                    });
                }
            } else if (m.includes("invalid") && (m.includes("password") || m.includes("email") || m.includes("credentials"))) {
                authErrorMessage.innerHTML = `${escapeHtml(msg)}. Don't have an account yet? <a href="#" id="linkSwitchToRegister" class="underline font-bold text-rose-800 ml-1">Register here →</a>`;
                const link = document.getElementById("linkSwitchToRegister");
                if (link) {
                    link.addEventListener("click", (e) => {
                        e.preventDefault();
                        setAuthMode("register");
                    });
                }
            } else {
                authErrorMessage.innerText = msg;
            }
            authErrorBanner.classList.remove("hidden");
        } else {
            alert(msg);
        }
    }

    // Handle Email & Password Login / Register securely via Backend API
    if (passwordAuthForm) {
        passwordAuthForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const email = inputAuthEmail.value.trim().toLowerCase();
            const password = inputAuthPassword.value;
            const fullName = inputAuthFullName ? inputAuthFullName.value.trim() : "";

            if (!email || !password) return;
            if (authErrorBanner) authErrorBanner.classList.add("hidden");

            btnSubmitAuth.disabled = true;
            const originalText = btnSubmitAuthText.innerText;
            btnSubmitAuthText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Authenticating...`;

            try {
                const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
                const payload = authMode === "login"
                    ? { email, password }
                    : { email, password, full_name: fullName };

                const res = await fetch(endpoint, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();

                if (!res.ok || data.status !== "success") {
                    showAuthError(data.detail || data.message || "Authentication failed. Please verify credentials.");
                    return;
                }

                const session = data.session;
                if (session && session.user) {
                    if (session.access_token) {
                        localStorage.setItem("supabase_auth_token", session.access_token);
                    }
                    applyUserSession(session.user);
                    if (accountModal) accountModal.classList.add("hidden");
                    showToast(authMode === "login" ? `Welcome back, ${currentUserEmail}!` : `Account created! Welcome, ${currentUserEmail}`);
                    await reloadAllUserData();
                } else {
                    showToast("Account ready. You can now log in.");
                    setAuthMode("login");
                }
            } catch (err) {
                showAuthError("Authentication error: " + err.message);
            } finally {
                btnSubmitAuth.disabled = false;
                btnSubmitAuthText.innerText = originalText;
            }
        });
    }

    // Sign Out Button
    if (btnSignOut) {
        btnSignOut.addEventListener("click", async () => {
            if (supabaseClient) {
                await supabaseClient.auth.signOut();
            }
            handleSignOutCleanup();
            showToast("Signed out. Switched to private guest space.");
            await reloadAllUserData();
        });
    }

    // Connect Supabase Database
    if (btnApplySupabase) {
        btnApplySupabase.addEventListener("click", async () => {
            const url = inputSupabaseUrl.value.trim();
            const key = inputSupabaseKey.value.trim();
            if (!url || !key) {
                alert("Please provide both Supabase Project URL and Anon Public Key.");
                return;
            }

            btnApplySupabase.disabled = true;
            btnApplySupabase.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Connecting...`;

            try {
                const res = await fetch("/api/config/supabase", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ supabase_url: url, supabase_key: key })
                });
                const data = await res.json();
                if (data.supabase_connected) {
                    showToast("Connected to Supabase PostgreSQL database!");
                    if (window.supabase) {
                        supabaseClient = window.supabase.createClient(url, key);
                        initSupabaseAuthListener();
                    }
                    await fetchStatus();
                    await reloadAllUserData();
                } else {
                    alert(data.message || "Could not connect to Supabase. Check URL and Key.");
                }
            } catch (err) {
                alert("Supabase connection error: " + err.message);
            } finally {
                btnApplySupabase.disabled = false;
                btnApplySupabase.innerHTML = `<i class="fa-solid fa-plug text-xs"></i> <span>Connect Supabase</span>`;
            }
        });
    }

    // Copy SQL Schema for Supabase
    if (btnCopySqlSchema) {
        btnCopySqlSchema.addEventListener("click", () => {
            const schemaSql = `-- ============================================================
-- Supabase Schema for Calendar AI (Multi-User + Hashes + Chat)
-- Paste and run this in Supabase Dashboard -> SQL Editor
-- ============================================================

-- 1. Create dedicated users table for account credentials & profiles
CREATE TABLE IF NOT EXISTS public.users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    auth_provider TEXT DEFAULT 'email',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Ensure user_id column exists on calendar_events
ALTER TABLE IF EXISTS public.calendar_events 
ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT 'guest';

-- 3. Ensure user_id column exists on hashed_vectors
ALTER TABLE IF EXISTS public.hashed_vectors 
ADD COLUMN IF NOT EXISTS user_id TEXT DEFAULT 'guest';

-- 4. Create hashed_vectors table if it doesn't exist yet
CREATE TABLE IF NOT EXISTS public.hashed_vectors (
    id TEXT PRIMARY KEY,
    user_id TEXT DEFAULT 'guest',
    raw_text TEXT NOT NULL,
    dimension INT NOT NULL DEFAULT 128,
    semantic_hash TEXT NOT NULL,
    vector_preview JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Create chat_messages table (Separate isolated chat history for every user)
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'guest',
    sender TEXT NOT NULL, -- 'user' or 'ai'
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Create fast lookup indexes
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON public.calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_hashed_vectors_user ON public.hashed_vectors(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_time ON public.chat_messages(user_id, created_at ASC);

-- 7. Enable Row Level Security (RLS) with open access
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hashed_vectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow all users" ON public.users;
CREATE POLICY "Allow all users" ON public.users FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all calendar_events" ON public.calendar_events;
CREATE POLICY "Allow all calendar_events" ON public.calendar_events FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all hashed_vectors" ON public.hashed_vectors;
CREATE POLICY "Allow all hashed_vectors" ON public.hashed_vectors FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all chat_messages" ON public.chat_messages;
CREATE POLICY "Allow all chat_messages" ON public.chat_messages FOR ALL USING (true);`;

            navigator.clipboard.writeText(schemaSql).then(() => {
                showToast("Copied updated SQL schema to clipboard! Paste into Supabase SQL editor.");
            }).catch(() => {
                alert("Failed to copy schema.");
            });
        });
    }

    if (btnConnectGoogleOAuth) {
        btnConnectGoogleOAuth.addEventListener("click", async () => {
            btnConnectGoogleOAuth.disabled = true;
            btnConnectGoogleOAuth.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Authorizing Google Calendar...`;
            try {
                const res = await fetch("/api/calendar/auth/connect", { method: "POST" });
                const data = await res.json();
                if (data.success) {
                    showToast(data.message || "Connected to Google Calendar!");
                    await fetchStatus();
                    await loadCalendarEvents();
                    await loadHashedTable();
                } else {
                    alert(data.message || "Google OAuth failed.");
                }
            } catch (err) {
                alert("Error: " + err.message);
            } finally {
                btnConnectGoogleOAuth.disabled = false;
                btnConnectGoogleOAuth.innerHTML = `<i class="fa-brands fa-google"></i> <span>Authorize with Google</span>`;
            }
        });
    }

    if (btnDisconnectGoogle) {
        btnDisconnectGoogle.addEventListener("click", async () => {
            if (!confirm("Disconnect from Google Calendar and switch back to local store?")) return;
            try {
                await fetch("/api/calendar/auth/disconnect", { method: "POST" });
                showToast("Disconnected from Google Calendar.");
                await fetchStatus();
                await loadCalendarEvents();
                await loadHashedTable();
            } catch (err) {
                alert("Error: " + err.message);
            }
        });
    }

    if (inputCredentialsFile) {
        inputCredentialsFile.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = async (ev) => {
                try {
                    const content = ev.target.result;
                    const res = await fetch("/api/calendar/auth/upload_credentials", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ content: content })
                    });
                    const data = await res.json();
                    if (data.status === "success") {
                        showToast("credentials.json uploaded successfully! Click 'Authorize' to connect.");
                        await fetchStatus();
                    } else {
                        alert("Upload error: " + data.detail);
                    }
                } catch (err) {
                    alert("Upload failed: " + err.message);
                }
            };
            reader.readAsText(file);
        });
    }

    if (btnApplyGroqKey) {
        btnApplyGroqKey.addEventListener("click", async () => {
            const key = inputGroqKey.value.trim();
            if (!key) return;
            try {
                await fetch("/api/config/keys", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ groq_api_key: key })
                });
                showToast("Groq API Key saved successfully!");
                await fetchStatus();
            } catch (err) {
                alert("Failed to save Groq Key: " + err.message);
            }
        });
    }
}

// Change Password Handlers
function setupChangePasswordHandlers() {
    const btnOpenChangePassword = document.getElementById("btnOpenChangePassword");
    const changePasswordModal = document.getElementById("changePasswordModal");
    const btnCloseChangePasswordModal = document.getElementById("btnCloseChangePasswordModal");
    const btnCancelChangePassword = document.getElementById("btnCancelChangePassword");
    const changePasswordForm = document.getElementById("changePasswordForm");
    const changePasswordUserLabel = document.getElementById("changePasswordUserLabel");
    const changePasswordErrorBanner = document.getElementById("changePasswordErrorBanner");
    const changePasswordErrorMessage = document.getElementById("changePasswordErrorMessage");
    const inputCurrentPassword = document.getElementById("inputCurrentPassword");
    const inputNewPassword = document.getElementById("inputNewPassword");
    const inputConfirmNewPassword = document.getElementById("inputConfirmNewPassword");
    const btnSubmitChangePassword = document.getElementById("btnSubmitChangePassword");

    if (btnOpenChangePassword && changePasswordModal) {
        btnOpenChangePassword.addEventListener("click", () => {
            if (changePasswordUserLabel) {
                changePasswordUserLabel.innerText = currentUserEmail || "Guest";
            }
            if (changePasswordErrorBanner) changePasswordErrorBanner.classList.add("hidden");
            if (changePasswordForm) changePasswordForm.reset();
            changePasswordModal.classList.remove("hidden");
            if (inputCurrentPassword) inputCurrentPassword.focus();
        });
    }

    function closeChangePassword() {
        if (changePasswordModal) changePasswordModal.classList.add("hidden");
    }

    if (btnCloseChangePasswordModal) btnCloseChangePasswordModal.addEventListener("click", closeChangePassword);
    if (btnCancelChangePassword) btnCancelChangePassword.addEventListener("click", closeChangePassword);

    if (changePasswordForm) {
        changePasswordForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const currentPassword = inputCurrentPassword.value;
            const newPassword = inputNewPassword.value;
            const confirmPassword = inputConfirmNewPassword.value;

            if (newPassword !== confirmPassword) {
                if (changePasswordErrorBanner && changePasswordErrorMessage) {
                    changePasswordErrorMessage.innerText = "New passwords do not match.";
                    changePasswordErrorBanner.classList.remove("hidden");
                } else {
                    alert("New passwords do not match.");
                }
                return;
            }

            if (newPassword.length < 6) {
                if (changePasswordErrorBanner && changePasswordErrorMessage) {
                    changePasswordErrorMessage.innerText = "New password must be at least 6 characters.";
                    changePasswordErrorBanner.classList.remove("hidden");
                } else {
                    alert("New password must be at least 6 characters.");
                }
                return;
            }

            btnSubmitChangePassword.disabled = true;
            btnSubmitChangePassword.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Updating...`;

            try {
                const res = await authFetch("/api/auth/change_password", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });

                const data = await res.json();
                if (!res.ok) {
                    if (changePasswordErrorBanner && changePasswordErrorMessage) {
                        changePasswordErrorMessage.innerText = data.detail || "Failed to update password.";
                        changePasswordErrorBanner.classList.remove("hidden");
                    } else {
                        alert(data.detail || "Failed to update password.");
                    }
                    return;
                }

                closeChangePassword();
                showToast("Password updated successfully!");
            } catch (err) {
                alert("Error changing password: " + err.message);
            } finally {
                btnSubmitChangePassword.disabled = false;
                btnSubmitChangePassword.innerHTML = `<i class="fa-solid fa-check"></i> <span>Update Password</span>`;
            }
        });
    }
}

// Utilities
function formatYmd(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function formatDateTimeLocal(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hours = String(d.getHours()).padStart(2, "0");
    const minutes = String(d.getMinutes()).padStart(2, "0");
    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function formatDateString(iso) {
    if (!iso) return "Date TBD";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTimeString(startIso, endIso) {
    if (!startIso) return "All Day";
    if (!startIso.includes("T")) return "All Day";
    if (startIso.includes("T00:00:00")) return "All Day";
    const s = new Date(startIso);
    if (isNaN(s.getTime())) return "All Day";
    const sStr = s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (!endIso || !endIso.includes("T") || endIso === startIso || endIso.includes("T00:00:00")) return sStr;
    const e = new Date(endIso);
    if (isNaN(e.getTime())) return sStr;
    const eStr = e.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return (sStr === eStr) ? sStr : `${sStr} - ${eStr}`;
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, m => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
    })[m]);
}

function formatMarkdown(text) {
    if (!text) return "";
    let formatted = escapeHtml(text);
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<b class="font-bold text-cream-900">$1</b>');
    formatted = formatted.replace(/\*(.*?)\*/g, '<i class="italic">$1</i>');
    formatted = formatted.replace(/\n\n/g, '<br><br>');
    formatted = formatted.replace(/\n• /g, '<br>• ');
    formatted = formatted.replace(/\n- /g, '<br>- ');
    return formatted;
}

function showToast(msg, duration = 3000) {
    const toast = document.createElement("div");
    toast.className = "fixed bottom-6 right-6 max-w-md bg-sage-800 text-white text-xs font-semibold px-4 py-3 rounded-2xl shadow-xl z-50 flex items-start gap-2.5 border border-sage-600 transition transform duration-300";
    
    // Convert URLs into clickable links
    let formattedMsg = escapeHtml(msg);
    formattedMsg = formattedMsg.replace(/(https:\/\/[^\s]+)/g, '<a href="$1" target="_blank" class="underline text-amber-300 hover:text-white font-bold ml-1">Open Activation Page &rarr;</a>');
    
    toast.innerHTML = `<i class="fa-solid fa-circle-info text-amber-300 mt-0.5 shrink-0"></i> <div class="flex-1">${formattedMsg}</div>`;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}
