// public/js/script.js

// --- Global TTS Variables ---
const synth = window.speechSynthesis;
let currentUtterance = null;
let currentPlayingButton = null;
let autoSlideInterval = null;

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM Loaded. Initializing...");
    loadNavbar().then(() => {
        console.log("Navbar loaded successfully. Proceeding with page setup.");
        setupSearch();
        initializePageContent();
    }).catch(error => {
        console.error("CRITICAL: Failed to load navbar. Functionality will be limited.", error);
    });
});

function initializePageContent() {
    // Determine page type and load appropriate data/setup listeners
    if (document.querySelector('.main-article')) {
        console.log("Article page detected");
        loadSidebarData();
        setupBrowserTTSListeners(); // Setup browser TTS listener
        setInterval(updateTimestamps, 60000); // Update 'time ago' periodically
        updateTimestamps(); // Initial update
    } else if (document.querySelector('.home-container')) {
        console.log("Homepage detected");
        loadHomepageData().then(() => {
            console.log("Homepage data loaded.");
            setupBrowserTTSListeners(); // Setup browser TTS after cards render
        }).catch(err => console.error("Error loading homepage data:", err));
        setInterval(updateTimestamps, 60000);
        updateTimestamps(); // Initial update
    } else if (document.querySelector('.page-container')) {
        console.log("Generic page detected (Latest, Topic, Search)");
         loadGenericPageData().then(() => {
            console.log("Generic page data loaded.");
            setupBrowserTTSListeners(); // Setup browser TTS after cards render
        }).catch(err => console.error("Error loading generic page data:", err));
        setInterval(updateTimestamps, 60000);
        updateTimestamps(); // Initial update
    } else {
        console.log("Page type not recognized for content loading.");
    }
}

// --- Timestamp Formatting ---
function timeAgo(isoDateString) {
    // Keep existing timeAgo function
    if (!isoDateString) return 'Date unknown'; try { const date = new Date(isoDateString); const now = new Date(); const seconds = Math.round((now - date) / 1000); if (isNaN(date)) return 'Invalid date'; if (seconds < 60) return `just now`; const minutes = Math.round(seconds / 60); if (minutes < 60) return `${minutes} min${minutes > 1 ? 's' : ''} ago`; const hours = Math.round(minutes / 60); if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`; const days = Math.round(hours / 24); if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`; const weeks = Math.round(days / 7); if (weeks < 5) return `${weeks} week${weeks > 1 ? 's' : ''} ago`; const months = Math.round(days / 30.44); if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`; const years = Math.round(days / 365.25); return `${years} year${years > 1 ? 's' : ''} ago`; } catch (e) { console.error("Date parse error:", isoDateString, e); return 'Date error'; }
}

function updateTimestamps() {
    // Keep existing updateTimestamps function
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
    // Keep existing loadNavbar function
    const navbarPlaceholder = document.getElementById('navbar-placeholder'); if (!navbarPlaceholder) { console.error("Navbar placeholder element (#navbar-placeholder) not found in the HTML."); document.body.insertAdjacentHTML('afterbegin', '<p style="color: red; text-align: center; background: #333; padding: 5px;">Error: Navbar placeholder missing in HTML!</p>'); return Promise.reject("Navbar placeholder missing"); } const navbarPath = '/navbar.html'; console.log(`Attempting to fetch navbar from: ${navbarPath}`); try { const response = await fetch(navbarPath, { cache: "no-store" }); console.log(`Fetch response status for ${navbarPath}: ${response.status}`); if (!response.ok) { console.error(`Failed to fetch ${navbarPath}. Status: ${response.status} ${response.statusText}`); response.text().then(text => console.error("Response body (if any):", text.substring(0, 500))); throw new Error(`Failed to fetch navbar. Status: ${response.status}`); } const navbarHtml = await response.text(); if (!navbarHtml || navbarHtml.trim().length < 20) { console.error(`Fetched navbar HTML from ${navbarPath} seems empty or invalid.`); throw new Error("Fetched navbar HTML is empty/invalid"); } navbarPlaceholder.innerHTML = navbarHtml; console.log("Navbar HTML successfully fetched and injected."); return Promise.resolve(); } catch (error) { console.error('Error details during navbar loading:', error); navbarPlaceholder.innerHTML = '<p style="color: red; text-align: center; padding: 10px;">Error loading navigation.</p>'; return Promise.reject(error); }
}

// --- Homepage Data Loading & Rendering ---
async function loadHomepageData() {
    // Keep existing loadHomepageData function
    console.log("Loading homepage data..."); const siteDataPath = '/site_data.json'; try { const response = await fetch(siteDataPath, { cache: "no-store" }); console.log(`Fetch status for ${siteDataPath}: ${response.status}`); if (!response.ok) throw new Error(`HTTP error fetching site_data! Status: ${response.status}`); const siteData = await response.json(); if (!siteData || typeof siteData !== 'object' || !Array.isArray(siteData.articles)) { console.error("Invalid site_data.json format. Expected object with 'articles' array.", siteData); throw new Error("site_data.json format error."); } const homepageArticles = siteData.articles; console.log(`Found ${homepageArticles.length} articles in site_data.json.`); renderBreakingNews(homepageArticles); renderLatestNews(homepageArticles); renderTopics(); renderTrendingNews(homepageArticles); updateTimestamps(); return Promise.resolve(); } catch (error) { console.error('Error loading or processing homepage data:', error); const b = document.querySelector('#breaking-news-section .breaking-news-content'); if(b) b.innerHTML = '<p class="placeholder error">Error loading breaking news.</p>'; const l = document.querySelector('#latest-news-section .latest-news-grid'); if(l) l.innerHTML = '<p class="placeholder error">Error loading latest news.</p>'; const t = document.querySelector('#topics-section .topics-list'); if(t) t.innerHTML = '<p class="placeholder error">Error loading topics.</p>'; const tr = document.querySelector('#trending-news-section .trending-news-list'); if(tr) tr.innerHTML = '<p class="placeholder error">Error loading trending news.</p>'; return Promise.reject(error); }
}

function renderBreakingNews(articles) {
    // Keep existing renderBreakingNews function
    const section = document.getElementById('breaking-news-section'); const container = document.getElementById('breaking-news-content'); const titleElement = document.getElementById('breaking-news-title'); if (!container || !titleElement || !section) { return; } container.innerHTML = ''; if (autoSlideInterval) { clearInterval(autoSlideInterval); autoSlideInterval = null; } const now = new Date(); const breakingArticles = articles.filter(a => a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6); let slidesData = []; let bannerTitle = "Breaking News"; let labelText = "Breaking"; let labelClass = ""; const MAX_BANNER_SLIDES = 5; if (breakingArticles.length > 0) { slidesData = breakingArticles.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Breaking News"; labelText = "Breaking"; labelClass = ""; } else { const nonBreaking = articles.filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6)).sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0)); if (nonBreaking.length > 0) { slidesData = nonBreaking.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Trending Now"; labelText = "Trending"; labelClass = "trending-label"; } else { section.style.display = 'none'; return; } } titleElement.textContent = bannerTitle; section.style.display = 'block'; slidesData.forEach((article, index) => { const linkPath = `/${article.link}`; const item = document.createElement('a'); item.href = linkPath; item.className = `breaking-news-item slider-item ${index === 0 ? 'active' : ''}`; item.innerHTML = `<span class="breaking-label ${labelClass}">${labelText}</span><img src="${article.image_url || 'https://via.placeholder.com/1200x400?text=News'}" alt="${article.title || 'News image'}" loading="lazy"><div class="breaking-news-text"><h3>${article.title || 'Untitled'}</h3><div class="breaking-news-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></div>`; container.appendChild(item); }); const slides = container.querySelectorAll('.slider-item'); if (slides.length > 1) { let currentSlideIndex = 0; const paginationContainer = document.createElement('div'); paginationContainer.className = 'slider-pagination'; const showSlide = (index) => { slides.forEach((slide, i) => slide.classList.toggle('active', i === index)); paginationContainer.querySelectorAll('.slider-dot').forEach((dot, i) => dot.classList.toggle('active', i === index)); currentSlideIndex = index; }; const nextSlide = () => showSlide((currentSlideIndex + 1) % slides.length); const prevSlide = () => showSlide((currentSlideIndex - 1 + slides.length) % slides.length); slides.forEach((_, index) => { const dot = document.createElement('button'); dot.className = 'slider-dot'; if (index === 0) dot.classList.add('active'); dot.setAttribute('aria-label', `Go to slide ${index + 1}`); dot.addEventListener('click', () => showSlide(index)); paginationContainer.appendChild(dot); }); container.appendChild(paginationContainer); const prevButton = document.createElement('button'); prevButton.className = 'slider-control slider-prev'; prevButton.innerHTML = '<i class="fas fa-chevron-left"></i>'; prevButton.title = "Previous"; prevButton.addEventListener('click', (e) => { e.preventDefault(); prevSlide(); }); container.appendChild(prevButton); const nextButton = document.createElement('button'); nextButton.className = 'slider-control slider-next'; nextButton.innerHTML = '<i class="fas fa-chevron-right"></i>'; nextButton.title = "Next"; nextButton.addEventListener('click', (e) => { e.preventDefault(); nextSlide(); }); container.appendChild(nextButton); const AUTO_SLIDE_INTERVAL_MS = 5000; autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS); container.addEventListener('mouseenter', () => { if(autoSlideInterval) { clearInterval(autoSlideInterval); }}); container.addEventListener('mouseleave', () => { if(autoSlideInterval) clearInterval(autoSlideInterval); autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS); }); } updateTimestamps();
}

function renderLatestNews(articles) {
    // Keep existing renderLatestNews function
    const container = document.querySelector('#latest-news-section .latest-news-grid'); if (!container) { return; } container.innerHTML = ''; const now = new Date(); const breakingIdsInBanner = Array.from(document.querySelectorAll('#breaking-news-content .breaking-news-item a')).map(a => a.getAttribute('href')); const nonBreakingArticles = articles.filter(a => { const isOldBreaking = a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6; const isInBanner = breakingIdsInBanner.includes(`/${a.link}`); return (!a.is_breaking || isOldBreaking) && !isInBanner; }); nonBreakingArticles.sort((a, b) => new Date(b.published_iso || 0) - new Date(a.published_iso || 0)); const articlesToShow = nonBreakingArticles.slice(0, 8); renderArticleCardList(container, articlesToShow, "No recent news available."); console.log(`Rendered latest news grid (${articlesToShow.length} articles).`);
}

function renderTopics() {
    // Keep existing renderTopics function
    const container = document.querySelector('#topics-section .topics-list'); if (!container) { return; } container.innerHTML = ''; const predefinedTopics = [ "AI Models", "Hardware", "Software", "Ethics", "Society", "Business", "Startups", "Regulation", "Robotics", "Research", "Open Source", "Health", "Finance", "Art & Media", "Compute" ]; if (predefinedTopics.length === 0) { container.innerHTML = '<p class="placeholder">No topics.</p>'; return; } predefinedTopics.forEach(topic => { const button = document.createElement('a'); button.href = `/topic.html?name=${encodeURIComponent(topic)}`; button.className = 'topic-button'; button.textContent = topic; container.appendChild(button); }); console.log("Rendered topics section.");
}

function renderTrendingNews(articles) {
    // Keep existing renderTrendingNews function
    const container = document.querySelector('#trending-news-section .trending-news-list'); if (!container) { return; } container.innerHTML = ''; if (!articles || articles.length === 0) { container.innerHTML = '<p class="placeholder">No articles available.</p>'; return; } const sortedByTrend = articles.slice().sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0)); const articlesToShow = sortedByTrend.slice(0, 4); if (articlesToShow.length === 0) { container.innerHTML = '<p class="placeholder">No trending news.</p>'; return; } const ul = document.createElement('ul'); ul.style.listStyle = 'none'; ul.style.padding = '0'; articlesToShow.forEach(article => { const li = document.createElement('li'); const linkPath = `/${article.link}`; li.innerHTML = `<a href="${linkPath}" class="sidebar-item-link"><div class="sidebar-item-image"><img src="${article.image_url || 'https://via.placeholder.com/80x60?text=N/A'}" alt="${article.title || ''}" loading="lazy"></div><div class="sidebar-item-content"><h3 class="sidebar-item-title">${article.title || 'Untitled'}</h3><span class="sidebar-item-time timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></a>`; ul.appendChild(li); }); container.appendChild(ul); console.log("Rendered trending news list."); updateTimestamps();
}

// --- Generic Page Data Loading ---
async function loadGenericPageData() {
    // Keep existing loadGenericPageData function
    const container = document.getElementById('page-content-area'); const titleElement = document.getElementById('page-title'); if (!container || !titleElement) { return; } container.innerHTML = '<p class="placeholder">Loading...</p>'; const urlParams = new URLSearchParams(window.location.search); const pagePath = window.location.pathname; const pageType = pagePath.substring(pagePath.lastIndexOf('/') + 1).split('.')[0]; const query = urlParams.get('q'); const topicName = urlParams.get('name'); let pageTitle = "News"; let articlesToDisplay = []; let emptyMessage = "No articles found."; let dataSourcePath = '/all_articles.json'; console.log(`Generic Page: type=${pageType}, source=${dataSourcePath}, query=${query}, topic=${topicName}`); try { const response = await fetch(dataSourcePath, { cache: "no-store" }); if (!response.ok) throw new Error(`HTTP error ${response.status}`); const fetchedData = await response.json(); if (!fetchedData?.articles) throw new Error(`Invalid JSON in ${dataSourcePath}`); const sourceArticles = fetchedData.articles; console.log(`Fetched ${sourceArticles.length} articles from ${dataSourcePath}`); if (pageType === 'latest') { pageTitle = "All News"; articlesToDisplay = sourceArticles; emptyMessage = "No news available."; } else if (pageType === 'topic' && topicName) { const decodedTopic = decodeURIComponent(topicName); pageTitle = `Topic: ${decodedTopic}`; articlesToDisplay = sourceArticles.filter(a => a.topic === decodedTopic || (a.tags && a.tags.includes(decodedTopic))); emptyMessage = `No articles found for topic "${decodedTopic}".`; } else if (pageType === 'search' && query) { pageTitle = `Search Results: "${query}"`; const tokens = query.toLowerCase().split(/[\s\W]+/).filter(Boolean); articlesToDisplay = sourceArticles.map(a => ({ ...a, score: calculateSearchScore(a, tokens) })).filter(a => a.score > 0).sort((a, b) => b.score - a.score); emptyMessage = `No results found for "${query}".`; } else { pageTitle = "Page Not Found"; emptyMessage = "Content not found."; articlesToDisplay = []; } titleElement.textContent = pageTitle; const siteName = document.title.split('-')[1]?.trim() || 'Dacoola'; document.title = `${pageTitle} - ${siteName}`; renderArticleCardList(container, articlesToDisplay, emptyMessage); return Promise.resolve(); } catch (error) { console.error(`Error loading data for generic page '${pageType}':`, error); titleElement.textContent = "Error"; container.innerHTML = '<p class="placeholder error">Could not load content.</p>'; return Promise.reject(error); }
}

function calculateSearchScore(article, searchTokens) {
    // Keep existing calculateSearchScore function
    let score = 0; const title = article.title?.toLowerCase() || ''; const topic = article.topic?.toLowerCase() || ''; const tags = (article.tags || []).map(t => t.toLowerCase()); const summary = article.summary_short?.toLowerCase() || ''; const combinedText = `${title} ${topic} ${tags.join(' ')} ${summary}`; const combinedTokens = combinedText.split(/[\s\W]+/).filter(Boolean); const queryPhrase = searchTokens.join(' '); for (const token of searchTokens) { if (!token) continue; if (title.includes(token)) score += 15; if (topic.includes(token)) score += 8; if (tags.some(tag => tag.includes(token))) score += 5; if (summary.includes(token)) score += 2; } if (title.includes(queryPhrase)) score += 50; else if (topic.includes(queryPhrase)) score += 25; else if (tags.some(tag => tag.includes(queryPhrase))) score += 15; else if (summary.includes(queryPhrase)) score += 10; if (searchTokens.every(token => combinedTokens.includes(token))) { score += 20; } return score;
}

// --- Renders a list of Article Cards ---
function renderArticleCardList(container, articles, emptyMessage) {
    // Keep existing renderArticleCardList function
    if (!container) { console.error("Target container not found for article list."); return; } container.innerHTML = ''; if (!articles || articles.length === 0) { container.innerHTML = `<p class="placeholder">${emptyMessage}</p>`; return; } let renderCount = 0; articles.forEach(article => { if (!article?.id || !article?.title || !article?.link) { console.warn("Skipping invalid article data:", article); return; } renderCount++; const card = document.createElement('article'); card.className = container.closest('.sidebar') ? 'article-card sidebar-card' : 'article-card'; const linkPath = `/${article.link}`; const topic = article.topic || "News"; const isBreaking = article.is_breaking || false; let showBreakingLabel = false; if (isBreaking && article.published_iso) { try { if ((new Date() - new Date(article.published_iso))/(1000*60*60) <= 6) showBreakingLabel = true; } catch {} } const audioButtonHtml = `<button class="listen-button no-audio" title="Listen to article title (Browser TTS)" data-article-id="${article.id}"><i class="fas fa-headphones"></i></button>`; card.innerHTML = ` ${showBreakingLabel ? '<span class="breaking-label">Breaking</span>' : ''} <div class="article-card-actions"> ${audioButtonHtml} </div> <a href="${linkPath}" class="article-card-link"> <div class="article-card-image"><img src="${article.image_url || 'https://via.placeholder.com/300x150?text=No+Image'}" alt="${article.title || 'News image'}" loading="lazy"></div> <div class="article-card-content"><h3>${article.title || 'Untitled'}</h3><div class="article-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span><span class="article-card-topic">${topic}</span></div></div> </a>`; container.appendChild(card); }); console.log(`Rendered ${renderCount} cards into container.`); setupBrowserTTSListeners(); updateTimestamps();
}


// --- Sidebar Data Loading & Rendering (For Article Pages) ---
async function loadSidebarData() {
    // Keep existing loadSidebarData function
    const relatedContainer = document.getElementById('related-news-content'); const latestContainer = document.getElementById('latest-news-content'); const mainArticleElement = document.querySelector('.main-article'); if (!mainArticleElement || (!relatedContainer && !latestContainer)) { return; } let currentArticleId = mainArticleElement.getAttribute('data-article-id'); let currentArticleTopic = mainArticleElement.getAttribute('data-article-topic'); let currentArticleTags = []; try { const tagsJson = mainArticleElement.getAttribute('data-article-tags'); if (tagsJson && tagsJson !== 'null' && tagsJson !== '[]') { currentArticleTags = JSON.parse(tagsJson); if (!Array.isArray(currentArticleTags)) currentArticleTags = []; } } catch (e) { console.error("Failed to parse tags for sidebar:", e); } console.log("Sidebar Context:", { id: currentArticleId, topic: currentArticleTopic, tags: currentArticleTags }); const allArticlesPath = '/all_articles.json'; console.log(`Sidebar: Attempting fetch from path: ${allArticlesPath}`); try { const response = await fetch(allArticlesPath, { cache: "no-store" }); console.log(`Sidebar: Fetch status for ${allArticlesPath}: ${response.status}`); if (!response.ok) { throw new Error(`HTTP error fetching sidebar data. Status: ${response.status}`); } const data = await response.json(); if (!data?.articles) throw new Error(`Invalid JSON format in sidebar data`); const allArticles = data.articles; if (latestContainer) { const latestSidebarArticles = allArticles.filter(a => a.id !== currentArticleId).slice(0, 5); renderArticleCardList(latestContainer, latestSidebarArticles, "No recent news."); console.log(`Rendered latest news sidebar (${latestSidebarArticles.length} articles).`); } if (relatedContainer) { let relatedArticles = []; if (currentArticleId && (currentArticleTopic || currentArticleTags.length > 0)) { relatedArticles = allArticles.filter(a => a.id !== currentArticleId).map(a => { let score = 0; if (a.topic === currentArticleTopic) score += 500; const sharedTags = (a.tags || []).filter(t => currentArticleTags.includes(t)).length; score += sharedTags * 50; if (a.published_iso) { try { const ageFactor = Math.max(0, 1 - (new Date() - new Date(a.published_iso))/(1000*60*60*24*30)); score += ageFactor * 10; } catch {} } return { ...a, score }; }).filter(a => a.score >= 10).sort((a, b) => b.score - a.score).slice(0, 5); } else { relatedArticles = allArticles.filter(a => a.id !== currentArticleId).slice(0, 5); console.warn("Related news fallback: No topic/tags context."); } renderArticleCardList(relatedContainer, relatedArticles, "No related news."); console.log(`Rendered related news sidebar (${relatedArticles.length} articles).`); } updateTimestamps(); } catch (err) { console.error('Error loading sidebar data:', err); if (latestContainer) latestContainer.innerHTML = '<p class="placeholder error">Error loading latest</p>'; if (relatedContainer) relatedContainer.innerHTML = '<p class="placeholder error">Error loading related</p>'; }
}

// --- Search Functionality ---
function setupSearch() {
    // Keep existing setupSearch function
    console.log("Running setupSearch()..."); const searchInput = document.getElementById('search-input'); const searchButton = document.getElementById('search-button'); const suggestionsContainer = document.getElementById('search-suggestions'); const searchContainer = document.querySelector('.nav-search'); if (!searchInput || !searchButton || !suggestionsContainer || !searchContainer) { console.warn("Search elements not found, skipping setup."); return; } searchContainer.style.position = 'relative'; let debounceTimeout; function debounce(func, delay) { return (...args) => { clearTimeout(debounceTimeout); debounceTimeout = setTimeout(() => func.apply(this, args), delay); }; } const showSuggestions = async (forceShow = false) => { const query = searchInput.value.trim().toLowerCase(); suggestionsContainer.innerHTML = ''; suggestionsContainer.style.display = 'none'; if (!forceShow && query.length < 1) return; const suggestDataPath = '/all_articles.json'; try { const resp = await fetch(suggestDataPath, {cache: "no-store"}); if (!resp.ok) throw new Error(`Suggest fetch fail ${resp.status}`); const data = await resp.json(); if (!data?.articles) return; let matches = []; const tokens = query.split(/[\s\W]+/).filter(Boolean); if (query.length > 0) { matches = data.articles.map(a => ({...a, score: calculateSearchScore(a, tokens)})).filter(a => a.score > 0).sort((a, b) => b.score - a.score).slice(0, 5); } else if (forceShow) { matches = data.articles.slice(0, 5); } if (matches.length > 0) { matches.forEach(a => { const link = document.createElement('a'); link.href = `/${a.link}`; link.className = 'suggestion-item'; link.innerHTML = `<img src="${a.image_url || 'https://via.placeholder.com/40x30?text=N/A'}" class="suggestion-image" alt="" loading="lazy"><div class="suggestion-text"><span class="suggestion-title">${a.title}</span><span class="suggestion-meta timestamp" data-iso-date="${a.published_iso||''}">${timeAgo(a.published_iso)}</span></div>`; suggestionsContainer.appendChild(link); }); suggestionsContainer.style.display = 'block'; updateTimestamps(); } } catch (err) { console.error("Suggest err:", err); } }; const redirectSearch = () => { const q = searchInput.value.trim(); if (q) window.location.href = `/search.html?q=${encodeURIComponent(q)}`; else searchInput.focus(); }; searchButton.addEventListener('click', redirectSearch); searchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); redirectSearch(); } }); searchInput.addEventListener('input', debounce(showSuggestions, 300)); searchInput.addEventListener('focus', () => showSuggestions(true)); document.addEventListener('click', (e) => { if (!searchContainer.contains(e.target)) suggestionsContainer.style.display = 'none'; });
}


// --- Browser TTS Playback Logic (Updates for Pause Icon) ---
function setupBrowserTTSListeners() {
    // Keep existing setupBrowserTTSListeners function
    if (!synth) { console.warn("Browser speech synthesis not supported."); return; } console.log("Setting up browser TTS event listeners..."); document.body.removeEventListener('click', handleTTSDelegatedClick); document.body.addEventListener('click', handleTTSDelegatedClick); const globalButton = document.getElementById('global-tts-player-button'); if (globalButton && currentPlayingButton !== globalButton) { resetTTSButtonState(globalButton); } else if (globalButton && synth.paused && currentPlayingButton === globalButton) { globalButton.innerHTML = '<i class="fas fa-play"></i>'; } document.querySelectorAll('.listen-button.playing').forEach(button => { if (button !== currentPlayingButton) { resetTTSButtonState(button); } }); window.removeEventListener('beforeunload', cancelSpeech); window.addEventListener('beforeunload', cancelSpeech);
}

function cancelSpeech() {
    // Keep existing cancelSpeech function
    if (!synth) return; if (synth.speaking || synth.pending) { console.log("Cancelling/clearing any active speech."); synth.cancel(); } if (currentPlayingButton) { resetTTSButtonState(currentPlayingButton); } currentUtterance = null; currentPlayingButton = null;
}

function resetTTSButtonState(button) {
    // Keep existing resetTTSButtonState function
    if (button) { button.classList.remove('playing', 'loading', 'paused'); button.innerHTML = '<i class="fas fa-headphones"></i>'; button.disabled = false; if (button === currentPlayingButton) { currentPlayingButton = null; currentUtterance = null; } }
}

// --- Modified handleTTSDelegatedClick ---
function handleTTSDelegatedClick(event) {
    const button = event.target.closest('.listen-button, #global-tts-player-button');
    if (!button || !synth) return;

    event.preventDefault();
    event.stopPropagation();

    let textToSpeak = '';
    const isGlobalButton = button.id === 'global-tts-player-button';

    // Determine text source
    if (isGlobalButton) {
        const articleBody = document.getElementById('article-body');
        textToSpeak = articleBody ? (articleBody.textContent || articleBody.innerText).trim() : '';
    } else {
        const card = button.closest('.article-card');
        const titleElement = card?.querySelector('h3');
        textToSpeak = titleElement ? (titleElement.textContent || titleElement.innerText).trim() : '';
    }

    // --- Playback Control Logic ---
    if (currentPlayingButton === button && currentUtterance) {
        // Clicked the currently active button
        if (synth.paused) {
            console.log("Attempting to RESUME TTS.");
            // *** Update icon immediately ***
            button.innerHTML = '<i class="fas fa-pause"></i>';
            button.classList.remove('paused');
            synth.resume();
        } else if (synth.speaking) {
            console.log("Attempting to PAUSE TTS.");
            // *** Update icon immediately ***
            button.innerHTML = '<i class="fas fa-play"></i>';
            button.classList.add('paused'); // Add paused class if needed for styling
            synth.pause();
        } else {
            // Neither speaking nor paused, but button was active? Reset.
            console.log("Synth inactive but button was active. Resetting.");
            cancelSpeech(); // Cancel and reset state fully
        }
    } else {
        // Clicked a new/inactive button
        console.log("Clicked inactive/new button. Cancelling previous and starting new speech.");
        cancelSpeech(); // Stop anything currently playing & reset state

        if (!textToSpeak) {
            console.warn("No text content found to speak for this item.");
            alert("No content available to speak for this item.");
            return;
        }
        speakText(textToSpeak, button); // Start speaking new text
    }
}


// --- Modified speakText ---
function speakText(text, button) {
    if (!synth || !text || !button) {
        console.error("speakText called with invalid arguments.", { text, button });
        if(button) resetTTSButtonState(button);
        return;
    }

    button.disabled = true;
    button.classList.remove('playing', 'paused'); // Ensure state classes are off
    button.classList.add('loading');
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const MAX_TTS_CHARS = 3000;
    if (text.length > MAX_TTS_CHARS) {
        console.warn(`Text too long (${text.length} chars), truncating for browser TTS.`);
        text = text.substring(0, MAX_TTS_CHARS - 3) + "...";
    }

    currentUtterance = new SpeechSynthesisUtterance(text);

    currentUtterance.onstart = () => {
        console.log("Browser speech started.");
        // Check if the button is still the intended target
        if (currentPlayingButton === button) {
            button.classList.remove('loading');
            button.classList.add('playing');
            // *** Set pause icon on start ***
            button.innerHTML = '<i class="fas fa-pause"></i>';
            button.disabled = false;
        } else {
             console.log("Speech started, but target button changed.");
        }
    };

    currentUtterance.onpause = () => {
        console.log("Browser speech paused.");
        if (currentPlayingButton === button) {
             // State change already handled in handleTTSDelegatedClick
             // Optionally ensure playing class is removed/paused added if needed
             // button.classList.remove('playing');
             button.classList.add('paused'); // Keep paused class
             button.disabled = false;
        }
    };

     currentUtterance.onresume = () => {
        console.log("Browser speech resumed.");
        if (currentPlayingButton === button) {
            // State change already handled in handleTTSDelegatedClick
             button.classList.remove('paused'); // Remove paused class
             button.classList.add('playing');
             button.disabled = false;
        }
    };


    currentUtterance.onend = () => {
        console.log("Browser Speech finished normally.");
        if (currentPlayingButton === button) {
            resetTTSButtonState(button); // Reset button fully
        } else {
             console.log("Speech ended, but it wasn't for the currently tracked button.");
        }
    };

    currentUtterance.onerror = (e) => {
        console.error('Browser Speech Synthesis Error:', e);
        if (e.error && e.error !== 'interrupted' && e.error !== 'canceled') {
            alert(`Speech error: ${e.error}`);
        } else {
             console.log("Speech error/interruption:", e.error || "Unknown error");
        }
        resetTTSButtonState(button); // Reset button on any error/cancel
    };

    // Associate the button with this utterance *before* speaking
    currentPlayingButton = button;
    synth.speak(currentUtterance);
}