// public/js/script.js

// --- Global TTS Variables ---
const synth = window.speechSynthesis;
let currentUtterance = null;
let currentPlayingButton = null; // Track button associated with active speech
let autoSlideInterval = null; // Interval ID for banner slider

document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM Loaded. Initializing...");
    // Load navbar first, it contains search elements needed by setupSearch
    loadNavbar().then(() => {
        setupSearch(); // Setup search functionality AFTER navbar is loaded

        // Determine page type and load appropriate data/setup listeners
        if (document.querySelector('.main-article')) {
            console.log("Article page detected");
            loadSidebarData();
            setupBrowserTTS(); // Setup TTS for global button on article pages
            setInterval(updateTimestamps, 60000);
        } else if (document.querySelector('.home-container')) {
            console.log("Homepage detected");
            loadHomepageData().then(() => setupBrowserTTS()); // Setup TTS after cards render
            setInterval(updateTimestamps, 60000);
        } else if (document.querySelector('.page-container')) {
            console.log("Generic page detected");
            loadGenericPageData().then(() => setupBrowserTTS()); // Setup TTS after cards render
            setInterval(updateTimestamps, 60000);
        } else {
            console.log("Page type not recognized.");
        }
    }).catch(error => {
        console.error("Failed to load navbar, search and subsequent initializations might fail.", error);
        // Still try to load content if possible, but search won't work reliably
        // Add fallback logic here if necessary
    });
});

// --- Timestamp Formatting ---
function timeAgo(isoDateString) {
    if (!isoDateString) return 'Date unknown'; try { const date = new Date(isoDateString); const now = new Date(); const seconds = Math.round((now - date) / 1000); if (isNaN(date)) return 'Invalid date'; if (seconds < 60) return `just now`; const minutes = Math.round(seconds / 60); if (minutes < 60) return `${minutes} min${minutes > 1 ? 's' : ''} ago`; const hours = Math.round(minutes / 60); if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`; const days = Math.round(hours / 24); if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`; const weeks = Math.round(days / 7); if (weeks < 5) return `${weeks} week${weeks > 1 ? 's' : ''} ago`; const months = Math.round(days / 30.44); if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`; const years = Math.round(days / 365.25); return `${years} year${years > 1 ? 's' : ''} ago`; } catch (e) { console.error("Date parse error:", isoDateString, e); return 'Date error'; }
}

function updateTimestamps() {
    document.querySelectorAll('.timestamp').forEach(el => {
        const isoDate = el.getAttribute('data-iso-date');
        if (isoDate) {
            const formattedTime = timeAgo(isoDate);
            if (el.textContent !== formattedTime) { el.textContent = formattedTime; try { el.setAttribute('title', new Date(isoDate).toLocaleString()); } catch { el.setAttribute('title', 'Invalid date'); } }
        }
    });
}

// --- Navbar Loading ---
async function loadNavbar() {
    const navbarPlaceholder = document.getElementById('navbar-placeholder');
    if (!navbarPlaceholder) {
        console.error("Navbar placeholder missing.");
        return Promise.reject("Navbar placeholder missing");
    }
    // Corrected Path: Assumes navbar.html is copied to the public directory root by your build process
    const navbarPath = '/navbar.html'; // <--- CORRECTED PATH
    try {
        console.log(`Fetching navbar: ${navbarPath}`);
        const response = await fetch(navbarPath);
        if (!response.ok) {
            throw new Error(`Failed fetch ${navbarPath}: ${response.status}`);
        }
        const navbarHtml = await response.text();
        navbarPlaceholder.innerHTML = navbarHtml;
        console.log("Navbar loaded.");
        return Promise.resolve();
    } catch (error) {
        console.error('Error loading navbar:', error);
        navbarPlaceholder.innerHTML = '<p style="color: red; text-align: center;">Error loading navigation</p>';
        return Promise.reject(error);
    }
}

// --- Homepage Data Loading ---
async function loadHomepageData() {
    console.log("Loading homepage data...");
    const siteDataPath = '/site_data.json'; // <--- CORRECTED PATH
    try {
        const response = await fetch(siteDataPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const siteData = await response.json();
        if (!siteData?.articles) throw new Error("site_data.json format error.");
        const homepageArticles = siteData.articles;
        console.log(`Found ${homepageArticles.length} articles for homepage sections.`);
        renderBreakingNews(homepageArticles);
        renderLatestNews(homepageArticles);
        renderTopics();
        renderTrendingNews(homepageArticles);
        updateTimestamps();
    } catch (error) {
        console.error('Error loading homepage data:', error);
        const b = document.querySelector('#breaking-news-section .breaking-news-content'); if(b) b.innerHTML = '<p class="placeholder error">Err breaking.</p>';
        const l = document.querySelector('#latest-news-section .latest-news-grid'); if(l) l.innerHTML = '<p class="placeholder error">Err latest.</p>';
        const t = document.querySelector('#topics-section .topics-list'); if(t) t.innerHTML = '<p class="placeholder error">Err topics.</p>';
        const tr = document.querySelector('#trending-news-section .trending-news-list'); if(tr) tr.innerHTML = '<p class="placeholder error">Err trending.</p>';
    }
}

// --- Renders Breaking News / Trending Banner Section ---
function renderBreakingNews(articles) {
    const section = document.getElementById('breaking-news-section'); const container = document.getElementById('breaking-news-content'); const titleElement = document.getElementById('breaking-news-title'); if (!container || !titleElement || !section) { console.error("Banner elements missing."); return; } container.innerHTML = ''; if (autoSlideInterval) { clearInterval(autoSlideInterval); autoSlideInterval = null; console.log("Cleared previous banner interval"); } const now = new Date(); const breakingArticles = articles.filter(a => a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6); let slidesData = []; let bannerTitle = "Breaking News"; let labelText = "Breaking"; let labelClass = ""; const MAX_BANNER_SLIDES = 5; if (breakingArticles.length > 0) { slidesData = breakingArticles.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Breaking News"; labelText = "Breaking"; labelClass = ""; } else { const nonBreaking = articles.filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6)); if (nonBreaking.length > 0) { slidesData = nonBreaking.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Trending Now"; labelText = "Trending"; labelClass = "trending-label"; } else { section.style.display = 'none'; return; } } titleElement.textContent = bannerTitle; section.style.display = 'block'; slidesData.forEach((article, index) => {
        const linkPath = `/${article.link}`; // <--- CORRECTED PATH
        const item = document.createElement('a'); item.href = linkPath; item.className = `breaking-news-item slider-item ${index === 0 ? 'active' : ''}`; item.innerHTML = `<span class="breaking-label ${labelClass}">${labelText}</span><img src="${article.image_url || 'https://via.placeholder.com/1200x400?text=News'}" alt="${article.title || 'News image'}" loading="lazy"><div class="breaking-news-text"><h3>${article.title || 'Untitled'}</h3><div class="breaking-news-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></div>`; container.appendChild(item); }); const slides = container.querySelectorAll('.slider-item'); if (slides.length > 1) { let currentSlideIndex = 0; const paginationContainer = document.createElement('div'); paginationContainer.className = 'slider-pagination'; const showSlide = (index) => { slides.forEach((slide, i) => slide.classList.toggle('active', i === index)); paginationContainer.querySelectorAll('.slider-dot').forEach((dot, i) => dot.classList.toggle('active', i === index)); currentSlideIndex = index; }; const nextSlide = () => showSlide((currentSlideIndex + 1) % slides.length); const prevSlide = () => showSlide((currentSlideIndex - 1 + slides.length) % slides.length); slides.forEach((_, index) => { const dot = document.createElement('button'); dot.className = 'slider-dot'; if (index === 0) dot.classList.add('active'); dot.setAttribute('aria-label', `Go to slide ${index + 1}`); dot.addEventListener('click', () => showSlide(index)); paginationContainer.appendChild(dot); }); container.appendChild(paginationContainer); const prevButton = document.createElement('button'); prevButton.className = 'slider-control slider-prev'; prevButton.innerHTML = '<i class="fas fa-chevron-left"></i>'; prevButton.title = "Previous"; prevButton.setAttribute('aria-label', 'Previous Slide'); prevButton.addEventListener('click', (e) => { e.preventDefault(); prevSlide(); }); container.appendChild(prevButton); const nextButton = document.createElement('button'); nextButton.className = 'slider-control slider-next'; nextButton.innerHTML = '<i class="fas fa-chevron-right"></i>'; nextButton.title = "Next"; nextButton.setAttribute('aria-label', 'Next Slide'); nextButton.addEventListener('click', (e) => { e.preventDefault(); nextSlide(); }); container.appendChild(nextButton); const AUTO_SLIDE_INTERVAL_MS = 5000; autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS); console.log(`Set banner interval: ${autoSlideInterval}`); container.addEventListener('mouseenter', () => { if(autoSlideInterval) { clearInterval(autoSlideInterval); console.log("Cleared banner interval on hover"); }}); container.addEventListener('mouseleave', () => { if(autoSlideInterval) clearInterval(autoSlideInterval); autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS); console.log(`Restarted banner interval on leave: ${autoSlideInterval}`); }); } updateTimestamps();
}

// --- Renders Latest News Grid on Homepage ---
function renderLatestNews(articles) {
    const container = document.querySelector('#latest-news-section .latest-news-grid');
    if (!container) { console.error("Latest news container not found."); return; }
    const now = new Date();
    const nonBreakingArticles = articles.filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6));
    const articlesToShow = nonBreakingArticles.slice(0, 8);
    renderArticleCardList(container, articlesToShow, "No recent news available.");
    console.log("Rendered latest news grid (up to 8).");
}

// --- Renders Topics Section on Homepage ---
function renderTopics() {
    const container = document.querySelector('#topics-section .topics-list'); if (!container) { console.error("Topics container missing."); return; } container.innerHTML = ''; const predefinedTopics = [ "AI Models", "Hardware", "Software", "Ethics", "Society", "Business", "Startups", "Regulation", "Robotics", "Research", "Open Source", "Health", "Finance", "Art & Media", "Compute" ]; if (predefinedTopics.length === 0) { container.innerHTML = '<p class="placeholder">No topics.</p>'; return; } predefinedTopics.forEach(topic => { const button = document.createElement('a');
    // Corrected Path: Link directly to topic.html from the root
    button.href = `/topic.html?name=${encodeURIComponent(topic)}`; // <--- CORRECTED PATH
    button.className = 'topic-button'; button.textContent = topic; container.appendChild(button); }); console.log("Rendered topics section.");
}

// --- Renders Trending News List on Homepage ---
function renderTrendingNews(articles) {
    const container = document.querySelector('#trending-news-section .trending-news-list');
    if (!container) { console.error("Trending news container not found."); return; }
    container.innerHTML = '';

    if (!articles || articles.length === 0) {
        container.innerHTML = '<p class="placeholder">No articles available for trending.</p>';
        return;
    }
    const sortedByTrend = articles.slice().sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0));
    const articlesToShow = sortedByTrend.slice(0, 4);

    if (articlesToShow.length === 0) {
        container.innerHTML = '<p class="placeholder">No trending news to display.</p>';
        return;
    }

    const ul = document.createElement('ul');
    ul.style.listStyle = 'none'; ul.style.padding = '0';

    articlesToShow.forEach(article => {
        const li = document.createElement('li');
        const linkPath = `/${article.link}`; // <--- CORRECTED PATH
        li.innerHTML = `
            <a href="${linkPath}" class="sidebar-item-link">
                <div class="sidebar-item-image">
                    <img src="${article.image_url || 'https://via.placeholder.com/80x60?text=N/A'}" alt="${article.title || ''}" loading="lazy">
                </div>
                <div class="sidebar-item-content">
                    <h3 class="sidebar-item-title">${article.title || 'Untitled'}</h3>
                    <span class="sidebar-item-time timestamp" data-iso-date="${article.published_iso || ''}">
                        ${timeAgo(article.published_iso)}
                    </span>
                </div>
            </a>`;
        ul.appendChild(li);
    });
    container.appendChild(ul);
    console.log("Rendered trending news list (using proxy score).");
    updateTimestamps();
}


// --- Generic Page Data Loading ---
async function loadGenericPageData() {
    const container = document.getElementById('page-content-area'); const titleElement = document.getElementById('page-title'); if (!container || !titleElement) { console.error("Generic page elements missing."); return; } container.innerHTML = '<p class="placeholder">Loading...</p>'; const urlParams = new URLSearchParams(window.location.search); const pagePath = window.location.pathname; const pageType = pagePath.substring(pagePath.lastIndexOf('/') + 1).split('.')[0]; const query = urlParams.get('q'); const topicName = urlParams.get('name'); let pageTitle = "News"; let articlesToDisplay = []; let emptyMessage = "No articles found.";
    // Corrected Path: Fetch data directly from root
    let dataSourcePath = (pageType === 'latest') ? '/all_articles.json' : '/site_data.json'; // <--- CORRECTED PATHS
    console.log(`Generic Page: type=${pageType}, source=${dataSourcePath}, query=${query}, topic=${topicName}`); try { const response = await fetch(dataSourcePath, { cache: "no-store" }); if (!response.ok) throw new Error(`HTTP error ${response.status}`); const fetchedData = await response.json(); if (!fetchedData?.articles) throw new Error(`Invalid JSON`); const sourceArticles = fetchedData.articles; console.log(`Fetched ${sourceArticles.length} from ${dataSourcePath}`); if (pageType === 'latest') { pageTitle = "All News"; articlesToDisplay = sourceArticles; emptyMessage = "No news available."; } else if (pageType === 'topic' && topicName) { const decodedTopic = decodeURIComponent(topicName); pageTitle = `Topic: ${decodedTopic}`; articlesToDisplay = sourceArticles.filter(a => a.topic === decodedTopic); emptyMessage = `No articles on topic "${decodedTopic}".`; } else if (pageType === 'search' && query) { pageTitle = `Search: "${query}"`; const tokens = query.toLowerCase().split(/[\s\W]+/).filter(Boolean); articlesToDisplay = sourceArticles.map(a => ({ ...a, score: calculateSearchScore(a, tokens) })).filter(a => a.score > 0).sort((a, b) => b.score - a.score); emptyMessage = `No results for "${query}".`; } else { pageTitle = "Not Found"; emptyMessage = "Content not found."; articlesToDisplay = []; } titleElement.textContent = pageTitle; const siteName = document.title.split('-')[1]?.trim() || 'Dacoola'; document.title = `${pageTitle} - ${siteName}`; renderArticleCardList(container, articlesToDisplay, emptyMessage); } catch (error) { console.error(`Error loading data page ${pageType}:`, error); titleElement.textContent = "Error"; container.innerHTML = '<p class="placeholder error">Could not load.</p>'; }
}

// --- REFINED Helper function for scoring search matches ---
function calculateSearchScore(article, searchTokens) {
    let score = 0;
    const title = article.title?.toLowerCase() || '';
    const topic = article.topic?.toLowerCase() || '';
    const tags = (article.tags || []).map(t => t.toLowerCase());
    const summary = article.summary_short?.toLowerCase() || '';
    const combinedText = `${title} ${topic} ${tags.join(' ')} ${summary}`;
    const combinedTokens = combinedText.split(/[\s\W]+/).filter(Boolean);
    const queryPhrase = searchTokens.join(' ');

    for (const token of searchTokens) {
        if (!token) continue;
        if (title.includes(token)) score += 10;
        if (topic.includes(token)) score += 5;
        if (tags.some(tag => tag.includes(token))) score += 3;
        if (summary.includes(token)) score += 1;
    }
    if (title.includes(queryPhrase)) score += 30;
    else if (topic.includes(queryPhrase)) score += 15;
    else if (tags.some(tag => tag.includes(queryPhrase))) score += 10;
    else if (summary.includes(queryPhrase)) score += 5;
    if (searchTokens.every(token => combinedTokens.includes(token))) {
        score += 15;
    }
    return score;
}


// --- Renders a list of Article Cards ---
function renderArticleCardList(container, articles, emptyMessage) {
    if (!container) { console.error("Target container not found for article list."); return; }
    container.innerHTML = '';
    console.log(`renderArticleCardList received ${articles?.length || 0} articles.`);

    if (!articles || articles.length === 0) {
        container.innerHTML = `<p class="placeholder">${emptyMessage}</p>`;
        return;
    }

    const isArticlePage = !!document.querySelector('.main-article');
    let renderCount = 0;

    articles.forEach(article => {
        if (!article || !article.id || !article.title) { console.warn("Skipping invalid article data:", article); return; }
        renderCount++;
        const card = document.createElement('article');
        card.className = container.closest('.sidebar') ? 'article-card sidebar-card' : 'article-card';
        // Corrected Path: Generate links relative to the root
        const linkPath = isArticlePage ? `../${article.link}` : `/${article.link}`; // <--- CORRECTED PATH
        const topic = article.topic || "News";
        const isBreaking = article.is_breaking || false;
        let showBreakingLabel = false;
        if (isBreaking && article.published_iso) { try { if ((new Date() - new Date(article.published_iso))/(1000*60*60) <= 6) showBreakingLabel = true; } catch {} }

        card.innerHTML = `
            ${showBreakingLabel ? '<span class="breaking-label">Breaking</span>' : ''}
            <div class="article-card-actions">
                <button class="listen-button" title="Listen to article" data-article-id="${article.id}"><i class="fas fa-headphones"></i></button>
            </div>
            <a href="${linkPath}" class="article-card-link">
                <div class="article-card-image">
                    <img src="${article.image_url || 'https://via.placeholder.com/300x150?text=No+Image'}" alt="${article.title || 'News image'}" loading="lazy">
                </div>
                <div class="article-card-content">
                    <h3>${article.title || 'Untitled'}</h3>
                    <div class="article-meta">
                        <span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span>
                        <span class="article-card-topic">${topic}</span>
                    </div>
                </div>
            </a>`;
        container.appendChild(card);
    });

    console.log(`renderArticleCardList actually rendered ${renderCount} cards.`);
    setupBrowserTTS();
    updateTimestamps();
}


// --- Sidebar Data Loading & Rendering (For Article Pages) ---
async function loadSidebarData() {
    const rC = document.getElementById('related-news-content'); const lC = document.getElementById('latest-news-content'); const mAE = document.querySelector('.main-article'); if (!mAE) { return; } let cId = mAE.getAttribute('data-article-id'); let cTop = mAE.getAttribute('data-article-topic'); let cTags = []; try { const tags = mAE.getAttribute('data-article-tags'); if (tags && tags !== 'null' && tags !== '[]') { cTags = JSON.parse(tags); if (!Array.isArray(cTags)) cTags = []; } } catch (e) { console.error("Tag parse err:", e); } console.log("Sidebar Context:", { id: cId, topic: cTop, tags: cTags }); if (!rC && !lC) return;
    const sdPath = '/site_data.json'; // <--- CORRECTED PATH
    try { const rsp = await fetch(sdPath, {cache:"no-store"}); if (!rsp.ok) throw new Error(`HTTP ${rsp.status}`); const sD = await rsp.json(); if (!sD?.articles) throw new Error("Data err"); const allA = sD.articles; if (lC) renderArticleCardList(lC, allA.slice(0, 5), "No recent."); if (rC) { let rel = []; if (cId && cTop) { rel = allA.filter(a => a.id !== cId).map(a => ({ ...a, score: (a.topic === cTop ? 1000 : 0) + ((a.tags||[]).filter(t => cTags.includes(t)).length * 10) + (a.published_iso ? (1 / (1 + (new Date() - new Date(a.published_iso))/(1000*60*60*24))) : 0) })).filter(a => a.score >= 10).sort((a, b) => b.score - a.score).slice(0, 5); } else { rel = allA.filter(a => a.id !== cId).slice(0, 5); console.warn("Rel fallback"); } renderArticleCardList(rC, rel, "No related."); } updateTimestamps(); } catch (err) { console.error('Sidebar err:', err); if (lC) lC.innerHTML = '<p class="placeholder error">Err</p>'; if (rC) rC.innerHTML = '<p class="placeholder error">Err</p>'; }
}


// --- Search Functionality ---
function setupSearch() {
    console.log("Running setupSearch()..."); const searchInput = document.getElementById('search-input'); const searchButton = document.getElementById('search-button'); const suggestionsContainer = document.getElementById('search-suggestions'); const searchContainer = document.querySelector('.nav-search'); if (!searchInput || !searchButton || !suggestionsContainer || !searchContainer) { console.warn("Search elements missing."); return; } searchContainer.style.position = 'relative'; let debounceTimeout; function debounce(func, delay) { return (...args) => { clearTimeout(debounceTimeout); debounceTimeout = setTimeout(() => func.apply(this, args), delay); }; } const showSuggestions = async (forceShow = false) => { const query = searchInput.value.trim().toLowerCase(); suggestionsContainer.innerHTML = ''; suggestionsContainer.style.display = 'none'; if (!forceShow && query.length < 1) return; try {
        const resp = await fetch('/all_articles.json', {cache: "no-store"}); // <--- CORRECTED PATH
        if (!resp.ok) throw new Error('Fetch fail'); const data = await resp.json(); if (!data?.articles) return; let matches = []; if (query.length > 0) { const tokens = query.split(/[\s\W]+/).filter(Boolean); matches = data.articles.map(a => ({...a, score: calculateSearchScore(a, tokens)})).filter(a => a.score > 0).sort((a, b) => b.score - a.score).slice(0, 5); } else if (forceShow) { matches = data.articles.slice(0, 5); } if (matches.length > 0) { matches.forEach(a => { const link = document.createElement('a');
        link.href = `/${a.link}`; // <--- CORRECTED PATH
        link.className = 'suggestion-item'; link.innerHTML = `<img src="${a.image_url || 'https://via.placeholder.com/40x30?text=N/A'}" class="suggestion-image" alt="" loading="lazy"><div class="suggestion-text"><span class="suggestion-title">${a.title}</span><span class="suggestion-meta timestamp" data-iso-date="${a.published_iso||''}">${timeAgo(a.published_iso)}</span></div>`; suggestionsContainer.appendChild(link); }); suggestionsContainer.style.display = 'block'; updateTimestamps(); } } catch (err) { console.error("Suggest err:", err); } }; const redirectSearch = () => { const q = searchInput.value.trim();
        // Corrected Path: search.html is at the root
        if (q) window.location.href = `/search.html?q=${encodeURIComponent(q)}`; // <--- CORRECTED PATH
        else searchInput.focus(); }; searchButton.addEventListener('click', redirectSearch); searchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); redirectSearch(); } }); searchInput.addEventListener('input', debounce(showSuggestions, 300)); searchInput.addEventListener('focus', () => showSuggestions(true)); document.addEventListener('click', (e) => { if (!searchContainer.contains(e.target)) suggestionsContainer.style.display = 'none'; });
}


// --- Browser TTS Playback Logic ---
function setupBrowserTTS() {
    if (!synth) { console.warn("Browser speech synthesis not supported."); return; }
    console.log("Setting up browser TTS listeners...");
    document.body.removeEventListener('click', handleTTSDelegatedClick);
    document.body.addEventListener('click', handleTTSDelegatedClick);
    const globalButton = document.getElementById('global-tts-player-button');
    if (globalButton) { resetTTSButtonState(globalButton); }
    window.removeEventListener('beforeunload', cancelSpeech);
    window.addEventListener('beforeunload', cancelSpeech);
}

function cancelSpeech() { if (synth.speaking) { console.log("Cancelling speech on unload."); synth.cancel(); } }

function resetTTSButtonState(button) { if (button) { button.classList.remove('playing'); button.innerHTML = '<i class="fas fa-headphones"></i>'; button.disabled = false; } }

function handleTTSDelegatedClick(event) {
    const button = event.target.closest('.listen-button, #global-tts-player-button');
    if (!button) return;
    event.preventDefault(); event.stopPropagation();
    let textToSpeak = ''; let articleId = button.getAttribute('data-article-id');

    if (button.id === 'global-tts-player-button') {
        const articleBody = document.getElementById('article-body');
        textToSpeak = articleBody ? (articleBody.textContent || articleBody.innerText).trim() : '';
         console.log(`Global button clicked for article ID (from body): ${document.querySelector('.main-article')?.getAttribute('data-article-id')}`);
    } else {
        const card = button.closest('.article-card');
        const titleElement = card?.querySelector('h3');
        textToSpeak = titleElement ? (titleElement.textContent || titleElement.innerText).trim() : '';
        console.log(`Card button clicked for article ID: ${articleId}`);
    }

    if (!textToSpeak) { alert("No content found to read."); return; }

    if (currentPlayingButton === button && synth.speaking) {
        console.log("Cancelling current speech (same button).");
        synth.cancel();
    } else {
        if (synth.speaking) { console.log("Something else speaking, cancelling first."); synth.cancel(); if(currentPlayingButton) resetTTSButtonState(currentPlayingButton); }
        setTimeout(() => speakText(textToSpeak, button), 150);
    }
}

function speakText(text, button) {
    if (!synth) return;
    currentUtterance = new SpeechSynthesisUtterance(text);
    currentUtterance.onerror = (e) => {
        console.error('Speech Error:', e);
        if (e.error !== 'interrupted') {
            alert(`Speech error: ${e.error}`);
        } else {
             console.log("Speech interrupted (likely by cancel or new request).");
        }
        resetTTSButtonState(button); currentPlayingButton = null; currentUtterance = null;
    };
    currentUtterance.onend = () => {
        console.log("Speech finished.");
        if(currentPlayingButton === button) {
             resetTTSButtonState(button);
             currentPlayingButton = null;
             currentUtterance = null;
        }
    };

    if (currentPlayingButton && currentPlayingButton !== button) { resetTTSButtonState(currentPlayingButton); }
    button.disabled = true; synth.speak(currentUtterance); button.classList.add('playing'); button.innerHTML = '<i class="fas fa-pause"></i>'; button.disabled = false; currentPlayingButton = button;
}