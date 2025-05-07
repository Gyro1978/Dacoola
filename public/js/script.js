// public/js/script.js (1/1)

// --- Global Variables ---
const synth = window.speechSynthesis; // For Browser TTS
let currentUtterance = null; // Currently speaking utterance
let currentPlayingButton = null; // Button associated with current TTS
let autoSlideInterval = null; // Interval timer for homepage banner

// -- Read values from CSS custom properties or use defaults --
const MAX_HOME_PAGE_ARTICLES = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--max-home-page-articles').trim() || '20', 10);
const LATEST_NEWS_GRID_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--latest-news-grid-count').trim() || '8', 10);
const TRENDING_NEWS_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--trending-news-count').trim() || '4', 10);
const SIDEBAR_DEFAULT_ITEM_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-default-item-count').trim() || '5', 10);
const AVG_SIDEBAR_ITEM_HEIGHT_PX = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--avg-sidebar-item-height').trim() || '110', 10);
const MAX_SIDEBAR_ITEMS = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--max-sidebar-items').trim() || '10', 10);

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM Loaded. Initializing...");
    loadNavbar().then(() => {
        console.log("Navbar loaded successfully. Proceeding with page setup.");
        setupSearch();
        initializePageContent();
        setupBrowserTTSListeners();
        setupFAQAccordion(); // Initialize FAQ interactivity
        setInterval(updateTimestamps, 60000);
        updateTimestamps();
    }).catch(error => {
        console.error("CRITICAL: Failed to load navbar. Functionality will be limited.", error);
    });
});

function initializePageContent() {
    const bodyClassList = document.body.classList;
    if (document.querySelector('.main-article')) {
        console.log("Article page detected");
        loadSidebarData();
    } else if (document.querySelector('.home-container')) {
        console.log("Homepage detected");
        loadHomepageData();
    } else if (bodyClassList.contains('page-404')) {
        console.log("404 page detected");
        loadLatestNewsFor404();
    } else if (document.querySelector('.page-container')) {
        console.log("Generic page detected (Latest, Topic, Search)");
        loadGenericPageData();
    } else {
        console.log("Page type not recognized for specific content loading.");
    }
}

// --- Data Loading & Rendering Functions ---
async function loadNavbar() {
    const navbarPlaceholder = document.getElementById('navbar-placeholder');
    if (!navbarPlaceholder) {
        console.error("Navbar placeholder element (#navbar-placeholder) not found.");
        document.body.insertAdjacentHTML('afterbegin', '<p style="color: red; text-align: center; background: #333; padding: 5px;">Error: Navbar placeholder missing!</p>');
        return Promise.reject("Navbar placeholder missing");
    }
    const navbarPath = '/navbar.html';
    try {
        const response = await fetch(navbarPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`Failed to fetch navbar. Status: ${response.status}`);
        const navbarHtml = await response.text();
        if (!navbarHtml || navbarHtml.trim().length < 20) throw new Error("Fetched navbar HTML is empty/invalid");
        navbarPlaceholder.innerHTML = navbarHtml;
        console.log("Navbar HTML successfully fetched and injected.");
    } catch (error) {
        console.error('Error details during navbar loading:', error);
        navbarPlaceholder.innerHTML = '<p style="color: red; text-align: center; padding: 10px;">Error loading navigation.</p>';
        return Promise.reject(error);
    }
}

async function loadHomepageData() {
    console.log("Loading homepage data...");
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const allData = await response.json();
        if (!allData?.articles) throw new Error("Invalid all_articles.json format.");
        const allArticles = allData.articles;
        const bannerAndTrendingArticles = allArticles.slice(0, MAX_HOME_PAGE_ARTICLES);
        renderBreakingNews(bannerAndTrendingArticles);
        const bannerArticleLinks = Array.from(document.querySelectorAll('#breaking-news-content a.breaking-news-item')).map(a => a.getAttribute('href'));
        const now = new Date();
        const articlesForGrid = allArticles.filter(a => {
            const isRecentBreaking = a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6;
            const isInBanner = bannerArticleLinks.includes(`/${a.link}`);
            return !isRecentBreaking && !isInBanner;
        }).slice(0, LATEST_NEWS_GRID_COUNT);
        renderLatestNewsGrid(articlesForGrid);
        renderTopics();
        renderTrendingNews(bannerAndTrendingArticles.slice(0, TRENDING_NEWS_COUNT));
    } catch (error) {
        console.error('Error loading homepage data:', error);
        const sel = s => document.querySelector(s);
        if (sel('#breaking-news-section .breaking-news-content')) sel('#breaking-news-section .breaking-news-content').innerHTML = '<p class="placeholder error">Error loading breaking news.</p>';
        if (sel('#latest-news-section .latest-news-grid')) sel('#latest-news-section .latest-news-grid').innerHTML = '<p class="placeholder error">Error loading latest news.</p>';
        if (sel('#topics-section .topics-list')) sel('#topics-section .topics-list').innerHTML = '<p class="placeholder error">Error loading topics.</p>';
        if (sel('#trending-news-section .trending-news-list')) sel('#trending-news-section .trending-news-list').innerHTML = '<p class="placeholder error">Error loading trending news.</p>';
    }
}

async function loadGenericPageData() {
    const container = document.getElementById('page-content-area');
    const titleElement = document.getElementById('page-title');
    if (!container || !titleElement) return;
    container.innerHTML = '<p class="placeholder">Loading...</p>';
    const urlParams = new URLSearchParams(window.location.search);
    const pagePath = window.location.pathname;
    const pageType = pagePath.substring(pagePath.lastIndexOf('/') + 1).split('.')[0];
    const query = urlParams.get('q');
    const topicName = urlParams.get('name');
    let pageTitle = "News", articlesToDisplay = [], emptyMessage = "No articles found.";
    const dataSourcePath = '/all_articles.json';
    try {
        const response = await fetch(dataSourcePath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        const fetchedData = await response.json();
        if (!fetchedData?.articles) throw new Error("Invalid JSON.");
        const sourceArticles = fetchedData.articles;
        if (pageType === 'latest') {
            pageTitle = "All News"; articlesToDisplay = sourceArticles; emptyMessage = "No news available.";
        } else if (pageType === 'topic' && topicName) {
            const decodedTopic = decodeURIComponent(topicName);
            pageTitle = `Topic: ${decodedTopic}`;
            articlesToDisplay = sourceArticles.filter(a => a.topic === decodedTopic || (a.tags && a.tags.includes(decodedTopic)));
            emptyMessage = `No articles for topic "${decodedTopic}".`;
        } else if (pageType === 'search' && query) {
            pageTitle = `Search: "${query}"`;
            const tokens = query.toLowerCase().split(/[\s\W]+/).filter(Boolean);
            articlesToDisplay = sourceArticles.map(a => ({ ...a, score: calculateSearchScore(a, tokens) })).filter(a => a.score > 0).sort((a, b) => b.score - a.score);
            emptyMessage = `No results for "${query}".`;
        } else {
            pageTitle = "Not Found"; emptyMessage = "Content not found.";
        }
        titleElement.textContent = pageTitle;
        document.title = `${pageTitle} - ${document.title.split(' - ')[1] || 'Dacoola'}`;
        renderArticleCardList(container, articlesToDisplay, emptyMessage);
    } catch (error) {
        console.error(`Error on generic page '${pageType}':`, error);
        titleElement.textContent = "Error"; container.innerHTML = '<p class="placeholder error">Could not load.</p>';
    }
}

async function loadLatestNewsFor404() {
    const container = document.getElementById('page-content-area');
    if (!container) return;
    container.innerHTML = '<p class="placeholder">Loading latest news...</p>';
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const allData = await response.json();
        if (!allData?.articles) throw new Error("Invalid all_articles.json format.");
        const latestArticles = allData.articles.slice(0, LATEST_NEWS_GRID_COUNT);
        renderArticleCardList(container, latestArticles, "No recent news available.");
    } catch (error) {
        console.error('Error loading latest news on 404:', error);
        container.innerHTML = '<p class="placeholder error">Error loading latest news.</p>';
    }
}

async function loadSidebarData() {
    const relatedContainer = document.getElementById('related-news-content');
    const latestContainer = document.getElementById('latest-news-content');
    const mainArticleElement = document.querySelector('.main-article');
    if (!mainArticleElement) {
        console.debug("Main article element not found, cannot load dynamic sidebars.");
        if (latestContainer) renderArticleCardList(latestContainer, [], "Loading news...");
        if (relatedContainer) renderArticleCardList(relatedContainer, [], "Loading related...");
        return;
    }
    if (!relatedContainer && !latestContainer) {
        console.debug("Sidebar containers for related/latest news not found.");
        return;
    }
    let currentArticleId = mainArticleElement.getAttribute('data-article-id');
    let currentArticleTopic = mainArticleElement.getAttribute('data-article-topic');
    let currentArticleTags = [];
    try {
        const tagsJson = mainArticleElement.getAttribute('data-article-tags');
        if (tagsJson && tagsJson.trim() !== '' && tagsJson !== 'null' && tagsJson !== '[]') {
            currentArticleTags = JSON.parse(tagsJson);
        }
        if (!Array.isArray(currentArticleTags)) currentArticleTags = [];
    } catch (e) { console.error("Failed to parse tags for sidebar:", e); currentArticleTags = []; }
    let numItemsForSidebarTarget = SIDEBAR_DEFAULT_ITEM_COUNT;
    try {
        const articleBody = document.getElementById('article-body');
        if (articleBody) {
            const mainArticleContentHeight = articleBody.offsetHeight;
            if (mainArticleContentHeight > 0 && AVG_SIDEBAR_ITEM_HEIGHT_PX > 0) {
                const calculatedItems = Math.floor(mainArticleContentHeight / AVG_SIDEBAR_ITEM_HEIGHT_PX);
                numItemsForSidebarTarget = Math.min(MAX_SIDEBAR_ITEMS, Math.max(SIDEBAR_DEFAULT_ITEM_COUNT, calculatedItems));
                if (calculatedItems > SIDEBAR_DEFAULT_ITEM_COUNT) {
                    numItemsForSidebarTarget = Math.min(MAX_SIDEBAR_ITEMS, calculatedItems + 1);
                }
            }
        }
    } catch (e) {
        console.warn("Could not calculate dynamic sidebar height, using default count.", e);
    }
    console.log(`Sidebar: Target items based on height: ${numItemsForSidebarTarget}`);
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error fetching sidebar data. Status: ${response.status}`);
        const data = await response.json();
        if (!data?.articles) throw new Error(`Invalid JSON format in sidebar data`);
        const allArticles = data.articles;
        let latestSidebarArticles_candidates = [];
        let relatedArticles_candidates = [];
        if (latestContainer) {
            latestSidebarArticles_candidates = allArticles.filter(a => a.id !== currentArticleId).slice(0, numItemsForSidebarTarget);
        }
        if (relatedContainer) {
            relatedArticles_candidates = allArticles.filter(a => a.id !== currentArticleId)
                .map(a => {
                    let score = 0;
                    if (a.topic === currentArticleTopic) score += 500;
                    const sharedTags = (a.tags || []).filter(t => currentArticleTags.includes(t)).length;
                    score += sharedTags * 50;
                    if (a.published_iso) { try { score += Math.max(0, 1 - (new Date() - new Date(a.published_iso))/(1000*60*60*24*30)) * 10; } catch {} }
                    return { ...a, score };
                })
                .filter(a => a.score >= 10).sort((a, b) => b.score - a.score).slice(0, numItemsForSidebarTarget);
        }
        let finalItemCount = numItemsForSidebarTarget;
        if (latestContainer && relatedContainer) {
            finalItemCount = Math.min(numItemsForSidebarTarget, latestSidebarArticles_candidates.length, relatedArticles_candidates.length);
            console.log(`Sidebar: Both containers present. Target: ${numItemsForSidebarTarget}, Latest Cands: ${latestSidebarArticles_candidates.length}, Related Cands: ${relatedArticles_candidates.length}. Final count for both: ${finalItemCount}.`);
        } else if (latestContainer) {
            finalItemCount = Math.min(numItemsForSidebarTarget, latestSidebarArticles_candidates.length);
            console.log(`Sidebar: Only Latest container. Target: ${numItemsForSidebarTarget}, Latest Cands: ${latestSidebarArticles_candidates.length}. Final count: ${finalItemCount}.`);
        } else if (relatedContainer) {
            finalItemCount = Math.min(numItemsForSidebarTarget, relatedArticles_candidates.length);
            console.log(`Sidebar: Only Related container. Target: ${numItemsForSidebarTarget}, Related Cands: ${relatedArticles_candidates.length}. Final count: ${finalItemCount}.`);
        }
        if (latestContainer) {
            const latestArticlesToRender = latestSidebarArticles_candidates.slice(0, finalItemCount);
            renderArticleCardList(latestContainer, latestArticlesToRender, "No recent news.");
        }
        if (relatedContainer) {
            const relatedArticlesToRender = relatedArticles_candidates.slice(0, finalItemCount);
            renderArticleCardList(relatedContainer, relatedArticlesToRender, "No related news.");
        }
    } catch (err) {
        console.error('Error loading sidebar data:', err);
        if (latestContainer) latestContainer.innerHTML = '<p class="placeholder error">Error loading latest</p>';
        if (relatedContainer) relatedContainer.innerHTML = '<p class="placeholder error">Error loading related</p>';
    }
}

// --- UI Rendering ---
function renderBreakingNews(articles) {
    const section = document.getElementById('breaking-news-section');
    const container = document.getElementById('breaking-news-content');
    const titleElement = document.getElementById('breaking-news-title');
    if (!container || !titleElement || !section) return;
    container.innerHTML = ''; if (autoSlideInterval) clearInterval(autoSlideInterval);
    const now = new Date();
    const breakingArticles = articles.filter(a => a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6);
    let slidesData = [], bannerTitle = "Breaking News", labelText = "Breaking", labelClass = "";
    const MAX_BANNER_SLIDES = 5;
    if (breakingArticles.length > 0) { slidesData = breakingArticles.slice(0, MAX_BANNER_SLIDES); }
    else {
        const nonBreaking = articles.filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6))
            .sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0));
        if (nonBreaking.length > 0) { slidesData = nonBreaking.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Trending Now"; labelText = "Trending"; labelClass = "trending-label"; }
        else { section.style.display = 'none'; return; }
    }
    titleElement.textContent = bannerTitle; section.style.display = 'block';
    slidesData.forEach((article, index) => {
        const linkPath = `/${article.link}`; const item = document.createElement('a'); item.href = linkPath;
        item.className = `breaking-news-item slider-item ${index === 0 ? 'active' : ''}`;
        item.innerHTML = `<span class="breaking-label ${labelClass}">${labelText}</span><img src="${article.image_url || 'https://via.placeholder.com/1200x400?text=News'}" alt="${article.title || 'News image'}" loading="lazy"><div class="breaking-news-text"><h3>${article.title || 'Untitled'}</h3><div class="breaking-news-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></div>`;
        container.appendChild(item);
    });
    const slides = container.querySelectorAll('.slider-item');
    if (slides.length > 1) {
        let currentSlideIndex = 0; const paginationContainer = document.createElement('div'); paginationContainer.className = 'slider-pagination';
        const showSlide = (index) => { slides.forEach((slide, i) => slide.classList.toggle('active', i === index)); paginationContainer.querySelectorAll('.slider-dot').forEach((dot, i) => dot.classList.toggle('active', i === index)); currentSlideIndex = index; };
        const nextSlide = () => showSlide((currentSlideIndex + 1) % slides.length);
        slides.forEach((_, index) => { const dot = document.createElement('button'); dot.className = 'slider-dot'; if (index === 0) dot.classList.add('active'); dot.setAttribute('aria-label', `Go to slide ${index + 1}`); dot.addEventListener('click', () => showSlide(index)); paginationContainer.appendChild(dot); }); container.appendChild(paginationContainer);
        const prevButton = document.createElement('button'); prevButton.className = 'slider-control slider-prev'; prevButton.innerHTML = '<i class="fas fa-chevron-left" aria-hidden="true"></i>'; prevButton.title="Previous"; prevButton.setAttribute('aria-label', 'Previous slide'); prevButton.addEventListener('click', (e) => { e.preventDefault(); showSlide((currentSlideIndex - 1 + slides.length) % slides.length); }); container.appendChild(prevButton);
        const nextButton = document.createElement('button'); nextButton.className = 'slider-control slider-next'; nextButton.innerHTML = '<i class="fas fa-chevron-right" aria-hidden="true"></i>'; nextButton.title="Next"; nextButton.setAttribute('aria-label', 'Next slide'); nextButton.addEventListener('click', (e) => { e.preventDefault(); nextSlide(); }); container.appendChild(nextButton);
        autoSlideInterval = setInterval(nextSlide, 5000);
        container.addEventListener('mouseenter', () => clearInterval(autoSlideInterval));
        container.addEventListener('mouseleave', () => { clearInterval(autoSlideInterval); autoSlideInterval = setInterval(nextSlide, 5000); });
    }
}

function renderLatestNewsGrid(articlesToRender) {
    const container = document.querySelector('#latest-news-section .latest-news-grid');
    if (!container) { console.error("Latest news grid container not found."); return; }
    renderArticleCardList(container, articlesToRender, "No recent news available.");
}

function renderTopics() {
    const container = document.querySelector('#topics-section .topics-list'); if (!container) { return; } container.innerHTML = '';
    const predefinedTopics = [ "AI Models", "Hardware", "Software", "Robotics", "Compute", "Research", "Open Source", "Business", "Startups", "Finance", "Health", "Society", "Ethics", "Regulation", "Art & Media", "Environment", "Education", "Security", "Gaming", "Transportation" ];
    if (predefinedTopics.length === 0) { container.innerHTML = '<p class="placeholder">No topics defined.</p>'; return; }
    predefinedTopics.forEach(topic => { const button = document.createElement('a'); button.href = `/topic.html?name=${encodeURIComponent(topic)}`; button.className = 'topic-button'; button.textContent = topic; container.appendChild(button); });
}

function renderTrendingNews(articles) {
    const container = document.querySelector('#trending-news-section .trending-news-list'); if (!container) return; container.innerHTML = '';
    if (!articles || articles.length === 0) { container.innerHTML = '<p class="placeholder">No articles.</p>'; return; }
    const sortedByTrend = articles.slice().sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0));
    const articlesToShow = sortedByTrend.slice(0, TRENDING_NEWS_COUNT);
    if (articlesToShow.length === 0) { container.innerHTML = '<p class="placeholder">No trending news.</p>'; return; }
    const ul = document.createElement('ul'); ul.className = 'trending-news-list-items';
    articlesToShow.forEach(article => {
        const li = document.createElement('li'); const linkPath = `/${article.link}`;
        li.innerHTML = `<a href="${linkPath}" class="sidebar-item-link"><div class="sidebar-item-image"><img src="${article.image_url || 'https://via.placeholder.com/80x60?text=N/A'}" alt="${article.title || ''}" loading="lazy"></div><div class="sidebar-item-content"><h3 class="sidebar-item-title">${article.title || 'Untitled'}</h3><span class="sidebar-item-time timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></a>`;
        ul.appendChild(li);
    }); container.appendChild(ul);
}

function renderArticleCardList(container, articles, emptyMessage) {
    if (!container) return; container.innerHTML = '';
    if (!articles || articles.length === 0) { container.innerHTML = `<p class="placeholder">${emptyMessage}</p>`; return; }
    articles.forEach(article => {
        if (!article?.id || !article?.title || !article?.link) { console.warn("Invalid article data for card:", article); return; }
        const card = document.createElement('article');
        card.className = container.closest('.sidebar') ? 'article-card sidebar-card' : 'article-card';
        const linkPath = `/${article.link}`; const topic = article.topic || "News";
        let showBreakingLabel = false;
        if (article.is_breaking && article.published_iso) { try { if ((new Date() - new Date(article.published_iso))/(1000*60*60) <= 6) showBreakingLabel = true; } catch {} }
        const audioButtonHtml = `<button class="listen-button no-audio" title="Listen to article title (Browser TTS)" data-article-id="${article.id}" aria-label="Listen to article title"><i class="fas fa-headphones" aria-hidden="true"></i></button>`;
        card.innerHTML = `${showBreakingLabel ? '<span class="breaking-label">Breaking</span>' : ''}<div class="article-card-actions">${audioButtonHtml}</div><a href="${linkPath}" class="article-card-link"><div class="article-card-image"><img src="${article.image_url || 'https://via.placeholder.com/300x150?text=No+Image'}" alt="${article.title || 'News image'}" loading="lazy"></div><div class="article-card-content"><h3>${article.title || 'Untitled'}</h3><div class="article-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span><span class="article-card-topic">${topic}</span></div></div></a>`;
        container.appendChild(card);
    });
}

// --- Utility & UI Interaction ---
function timeAgo(isoDateString) {
    if (!isoDateString) return 'Date unknown'; try { const date = new Date(isoDateString); if (isNaN(date)) return 'Invalid date'; const now = new Date(); const seconds = Math.round((now - date) / 1000); if (seconds < 60) return `just now`; const minutes = Math.round(seconds / 60); if (minutes < 60) return `${minutes} min${minutes > 1 ? 's' : ''} ago`; const hours = Math.round(minutes / 60); if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`; const days = Math.round(hours / 24); if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`; const weeks = Math.round(days / 7); if (weeks < 5) return `${weeks} week${weeks > 1 ? 's' : ''} ago`; const months = Math.round(days / 30.44); if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`; const years = Math.round(days / 365.25); return `${years} year${years > 1 ? 's' : ''} ago`; } catch (e) { console.error("Date parse error:", isoDateString, e); return 'Date error'; }
}
function updateTimestamps() {
    document.querySelectorAll('.timestamp').forEach(el => { const isoDate = el.getAttribute('data-iso-date'); if (isoDate) { const formattedTime = timeAgo(isoDate); if (el.textContent !== formattedTime) { el.textContent = formattedTime; try { el.setAttribute('title', new Date(isoDate).toLocaleString()); } catch { el.setAttribute('title', 'Invalid date'); } } } });
}
function calculateSearchScore(article, searchTokens) {
    let score = 0; const title = article.title?.toLowerCase() || ''; const topic = article.topic?.toLowerCase() || ''; const tags = (article.tags || []).map(t => t.toLowerCase()); const summary = article.summary_short?.toLowerCase() || ''; const text = `${title} ${topic} ${tags.join(' ')} ${summary}`; const textTokens = text.split(/[\s\W]+/).filter(Boolean); const qPhrase = searchTokens.join(' ');
    for (const token of searchTokens) { if (!token) continue; if (title.includes(token)) score += 15; if (topic.includes(token)) score += 8; if (tags.some(tag => tag.includes(token))) score += 5; if (summary.includes(token)) score += 2; }
    if (title.includes(qPhrase)) score += 50; else if (topic.includes(qPhrase)) score += 25; else if (tags.some(tag => tag.includes(qPhrase))) score += 15; else if (summary.includes(qPhrase)) score += 10;
    if (searchTokens.every(token => textTokens.includes(token))) score += 20; return score;
}
function setupSearch() {
    const searchInput = document.getElementById('search-input'), searchButton = document.getElementById('search-button'), suggestionsContainer = document.getElementById('search-suggestions'), searchContainer = document.querySelector('.nav-search');
    if (!searchInput || !searchButton || !suggestionsContainer || !searchContainer) { console.warn("Search elements missing."); return; }
    searchContainer.style.position = 'relative'; let debounceTimeout; const debounce = (func, delay) => (...args) => { clearTimeout(debounceTimeout); debounceTimeout = setTimeout(() => func.apply(this, args), delay); };
    const showSuggestions = async (forceShow = false) => {
        const query = searchInput.value.trim().toLowerCase(); suggestionsContainer.innerHTML = ''; suggestionsContainer.style.display = 'none'; if (!forceShow && query.length < 1) return;
        try { const resp = await fetch('/all_articles.json', {cache: "no-store"}); if (!resp.ok) throw new Error("Fetch fail"); const data = await resp.json(); if (!data?.articles) return; let matches = [];
            if (query.length > 0) { const tokens = query.split(/[\s\W]+/).filter(Boolean); matches = data.articles.map(a=>({...a, score: calculateSearchScore(a,tokens)})).filter(a=>a.score > 0).sort((a,b)=>b.score-a.score).slice(0,5); }
            else if (forceShow) { matches = data.articles.slice(0,5); }
            if (matches.length > 0) { matches.forEach(a => { const link = document.createElement('a'); link.href = `/${a.link}`; link.className = 'suggestion-item'; link.innerHTML = `<img src="${a.image_url || 'https://via.placeholder.com/80x50?text=N/A'}" class="suggestion-image" alt="" loading="lazy"><div class="suggestion-text"><span class="suggestion-title">${a.title}</span><span class="suggestion-meta timestamp" data-iso-date="${a.published_iso||''}">${timeAgo(a.published_iso)}</span></div>`; suggestionsContainer.appendChild(link); }); suggestionsContainer.style.display = 'block'; updateTimestamps(); }
        } catch (err) { console.error("Suggest err:", err); }
    };
    const redirectSearch = () => { const q = searchInput.value.trim(); if (q) window.location.href = `/search.html?q=${encodeURIComponent(q)}`; else searchInput.focus(); };
    searchButton.addEventListener('click', redirectSearch); searchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); redirectSearch(); } });
    searchInput.addEventListener('input', debounce(showSuggestions, 300)); searchInput.addEventListener('focus', () => showSuggestions(true));
    document.addEventListener('click', (e) => { if (!searchContainer.contains(e.target)) suggestionsContainer.style.display = 'none'; });
}

function setupFAQAccordion() {
    const faqSections = document.querySelectorAll('#article-body .faq-section');
    faqSections.forEach(faqSection => {
        const faqItems = faqSection.querySelectorAll('details.faq-item');
        if (faqItems.length > 0) {
            console.log("Setting up FAQ accordion for", faqItems.length, "items (multiple allowed).");
            // No need to add individual event listeners if we are not closing others
            // The default <details> behavior allows multiple to be open.
        }
    });
}


// --- Browser TTS Playback Logic ---
function setupBrowserTTSListeners() {
    if (!synth) { console.warn("Browser TTS not supported."); document.querySelectorAll('.listen-button, #global-tts-player-button').forEach(btn => btn.style.display = 'none'); return; }
    console.log("Setting up browser TTS listeners...");
    document.body.removeEventListener('click', handleTTSDelegatedClick);
    document.body.addEventListener('click', handleTTSDelegatedClick);
    const globalButton = document.getElementById('global-tts-player-button');
    if (globalButton) {
        globalButton.setAttribute('aria-label', 'Listen to main article content');
        if (currentPlayingButton !== globalButton) resetTTSButtonState(globalButton);
        else if (synth.paused) globalButton.innerHTML = '<i class="fas fa-play" aria-hidden="true"></i>';
    }
    document.querySelectorAll('.listen-button.playing').forEach(button => { if (button !== currentPlayingButton) resetTTSButtonState(button); });
    window.addEventListener('beforeunload', cancelSpeech);
}

function handleTTSDelegatedClick(event) {
    const button = event.target.closest('.listen-button, #global-tts-player-button');
    if (!button || !synth) return;
    event.preventDefault(); event.stopPropagation();
    let textToSpeak = ''; const isGlobalButton = button.id === 'global-tts-player-button';
    if (isGlobalButton) { const articleBody = document.getElementById('article-body'); textToSpeak = articleBody ? (articleBody.innerText || articleBody.textContent).trim() : ''; if(!textToSpeak){ const headline = document.getElementById('article-headline'); textToSpeak = headline ? (headline.innerText || headline.textContent).trim() : '';}}
    else { const card = button.closest('.article-card'); const titleElement = card?.querySelector('h3'); textToSpeak = titleElement ? (titleElement.innerText || titleElement.textContent).trim() : ''; }

    if (currentPlayingButton === button && currentUtterance) {
        if (synth.paused) { console.log("RESUME TTS."); button.innerHTML = '<i class="fas fa-pause" aria-hidden="true"></i>'; button.setAttribute('aria-label', 'Pause audio narration'); button.classList.remove('paused'); synth.resume(); }
        else if (synth.speaking) { console.log("PAUSE TTS."); button.innerHTML = '<i class="fas fa-play" aria-hidden="true"></i>'; button.setAttribute('aria-label', 'Resume audio narration'); button.classList.add('paused'); synth.pause(); }
        else { cancelSpeech(); }
    } else {
        cancelSpeech();
        if (!textToSpeak) { console.warn("No text for TTS."); alert("No content to read."); resetTTSButtonState(button); return; }
        speakText(textToSpeak, button);
    }
}
function speakText(text, button) {
    if (!synth || !text || !button) { if(button) resetTTSButtonState(button); return; }
    button.disabled = true; button.classList.remove('playing', 'paused'); button.classList.add('loading');
    button.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>'; button.setAttribute('aria-label', 'Loading audio narration');
    const MAX_TTS_CHARS = 3000; if (text.length > MAX_TTS_CHARS) text = text.substring(0, MAX_TTS_CHARS - 3) + "...";
    currentUtterance = new SpeechSynthesisUtterance(text); currentPlayingButton = button;
    currentUtterance.onstart = () => { if (currentPlayingButton === button) { button.classList.remove('loading'); button.classList.add('playing'); button.innerHTML = '<i class="fas fa-pause" aria-hidden="true"></i>'; button.setAttribute('aria-label', 'Pause audio narration'); button.disabled = false; }};
    currentUtterance.onpause = () => { if (currentPlayingButton === button) button.classList.add('paused'); };
    currentUtterance.onresume = () => { if (currentPlayingButton === button) { button.classList.remove('paused'); button.classList.add('playing'); }};
    currentUtterance.onend = () => { if (currentPlayingButton === button) resetTTSButtonState(button); currentUtterance = null; currentPlayingButton = null; };
    currentUtterance.onerror = (e) => { console.error('TTS Error:', e); if (e.error && e.error !== 'interrupted' && e.error !== 'canceled') alert(`Speech error: ${e.error}`); resetTTSButtonState(button); if (currentPlayingButton === button) { currentUtterance = null; currentPlayingButton = null; }};
    synth.speak(currentUtterance);
}
function resetTTSButtonState(button) {
    if (button) {
        button.classList.remove('playing', 'loading', 'paused');
        button.innerHTML = '<i class="fas fa-headphones" aria-hidden="true"></i>';
        button.disabled = false;
        const defaultListenLabel = button.id === 'global-tts-player-button' ? 'Listen to main article content' : 'Listen to article title';
        button.setAttribute('aria-label', defaultListenLabel);
    }
}
function cancelSpeech() {
    if (!synth) return; if (synth.speaking || synth.pending) synth.cancel();
    if (currentPlayingButton) resetTTSButtonState(currentPlayingButton);
    currentUtterance = null; currentPlayingButton = null;
}