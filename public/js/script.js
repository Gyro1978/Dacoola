// public/js/script.js

// --- Global Variables ---
const synth = window.speechSynthesis; // For Browser TTS
let currentUtterance = null; // Currently speaking utterance
let currentPlayingButton = null; // Button associated with current TTS
let autoSlideInterval = null; // Interval timer for homepage banner
const MAX_HOME_PAGE_ARTICLES = 20; // Max articles on homepage grid (set in workflow)
const LATEST_NEWS_COUNT = 8;      // Number of articles for "Latest News" sections

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM Loaded. Initializing...");
    // Load navbar first, then initialize page content
    loadNavbar().then(() => {
        console.log("Navbar loaded successfully. Proceeding with page setup.");
        setupSearch(); // Setup search bar functionality
        initializePageContent(); // Load content based on page type
        setupBrowserTTSListeners(); // Setup listeners for TTS buttons globally
        setInterval(updateTimestamps, 60000); // Update timestamps every minute
        updateTimestamps(); // Initial timestamp update
    }).catch(error => {
        console.error("CRITICAL: Failed to load navbar. Functionality will be limited.", error);
        // Optionally try to initialize content even if navbar fails
        // initializePageContent();
        // setupBrowserTTSListeners();
    });
});

/**
 * Determines the type of page and calls the appropriate content loading function.
 */
function initializePageContent() {
    const bodyClassList = document.body.classList;

    if (document.querySelector('.main-article')) {
        console.log("Article page detected");
        loadSidebarData(); // Load sidebars for related/latest news
    } else if (document.querySelector('.home-container')) {
        console.log("Homepage detected");
        loadHomepageData(); // Load all homepage sections
    } else if (bodyClassList.contains('page-404')) { // <<< Check for 404 page class >>>
        console.log("404 page detected");
        loadLatestNewsFor404(); // <<< Call specific function for 404 >>>
    } else if (document.querySelector('.page-container')) { // Generic page check (last)
        console.log("Generic page detected (Latest, Topic, Search)");
        loadGenericPageData(); // Load article list for these pages
    } else {
        console.log("Page type not recognized for specific content loading.");
    }
    // TTS listeners and timestamps are handled after loadNavbar in the DOMContentLoaded event
}

// --- Data Loading & Rendering Functions ---

/**
 * Fetches navbar HTML and injects it into the placeholder.
 */
async function loadNavbar() {
    const navbarPlaceholder = document.getElementById('navbar-placeholder');
    if (!navbarPlaceholder) {
        console.error("Navbar placeholder element (#navbar-placeholder) not found.");
        // Optionally display an error message on the page itself
        document.body.insertAdjacentHTML('afterbegin', '<p style="color: red; text-align: center; background: #333; padding: 5px;">Error: Navbar placeholder missing!</p>');
        return Promise.reject("Navbar placeholder missing");
    }

    const navbarPath = '/navbar.html'; // Path relative to web root
    console.log(`Attempting to fetch navbar from: ${navbarPath}`);
    try {
        // Use cache: "no-store" to always get the latest navbar during development/testing if needed
        const response = await fetch(navbarPath, { cache: "no-store" });
        console.log(`Fetch response status for ${navbarPath}: ${response.status}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch navbar. Status: ${response.status}`);
        }
        const navbarHtml = await response.text();
        if (!navbarHtml || navbarHtml.trim().length < 20) { // Basic check for empty content
            throw new Error("Fetched navbar HTML is empty or invalid");
        }
        navbarPlaceholder.innerHTML = navbarHtml;
        console.log("Navbar HTML successfully fetched and injected.");
        return Promise.resolve(); // Signal success
    } catch (error) {
        console.error('Error details during navbar loading:', error);
        navbarPlaceholder.innerHTML = '<p style="color: red; text-align: center; padding: 10px;">Error loading navigation.</p>';
        return Promise.reject(error); // Signal failure
    }
}

/**
 * Loads and renders all sections for the homepage.
 */
async function loadHomepageData() {
    console.log("Loading homepage data...");
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error fetching all_articles! Status: ${response.status}`);
        const allData = await response.json();
        if (!allData?.articles) throw new Error("Invalid all_articles.json format.");

        const allArticles = allData.articles;
        const homepageArticles = allArticles.slice(0, MAX_HOME_PAGE_ARTICLES); // Limit for banner/trending
        const latestGridArticles = allArticles.slice(0, LATEST_NEWS_COUNT); // Limit for main grid

        console.log(`Loaded ${allArticles.length} total articles, using ${homepageArticles.length} for banner/trending and ${latestGridArticles.length} for latest grid.`);

        renderBreakingNews(homepageArticles);
        renderLatestNewsGrid(latestGridArticles); // Use specific function for grid
        renderTopics();
        renderTrendingNews(homepageArticles);
        // Timestamps updated globally after initialization

    } catch (error) {
        console.error('Error loading or processing homepage data:', error);
        // <<< CORRECTED CATCH BLOCK >>>
        // Display errors in placeholders if the element exists
        const breakingContainer = document.querySelector('#breaking-news-section .breaking-news-content');
        if (breakingContainer) breakingContainer.innerHTML = '<p class="placeholder error">Error loading breaking news.</p>';

        const latestContainer = document.querySelector('#latest-news-section .latest-news-grid');
        if (latestContainer) latestContainer.innerHTML = '<p class="placeholder error">Error loading latest news.</p>';

        const topicsContainer = document.querySelector('#topics-section .topics-list');
        if (topicsContainer) topicsContainer.innerHTML = '<p class="placeholder error">Error loading topics.</p>';

        const trendingContainer = document.querySelector('#trending-news-section .trending-news-list');
        if (trendingContainer) trendingContainer.innerHTML = '<p class="placeholder error">Error loading trending news.</p>';
        // <<< END CORRECTED CATCH BLOCK >>>
    }
}

/**
 * Loads and renders the main content area for generic list pages (Latest, Topic, Search).
 */
async function loadGenericPageData() {
    const container = document.getElementById('page-content-area');
    const titleElement = document.getElementById('page-title');
    if (!container || !titleElement) {
        console.error("Required elements #page-content-area or #page-title not found for generic page.");
        return;
    }
    container.innerHTML = '<p class="placeholder">Loading...</p>';

    const urlParams = new URLSearchParams(window.location.search);
    const pagePath = window.location.pathname;
    const pageType = pagePath.substring(pagePath.lastIndexOf('/') + 1).split('.')[0];
    const query = urlParams.get('q');
    const topicName = urlParams.get('name');

    let pageTitle = "News";
    let articlesToDisplay = [];
    let emptyMessage = "No articles found.";
    const dataSourcePath = '/all_articles.json';
    console.log(`Generic Page: type=${pageType}, source=${dataSourcePath}, query=${query}, topic=${topicName}`);

    try {
        const response = await fetch(dataSourcePath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error ${response.status}`);
        const fetchedData = await response.json();
        if (!fetchedData?.articles) throw new Error(`Invalid JSON in ${dataSourcePath}`);
        const sourceArticles = fetchedData.articles;
        console.log(`Fetched ${sourceArticles.length} articles from ${dataSourcePath}`);

        // Filter/Sort based on page type
        if (pageType === 'latest') {
            pageTitle = "All News";
            articlesToDisplay = sourceArticles; // Already sorted newest first in JSON
            emptyMessage = "No news available.";
        } else if (pageType === 'topic' && topicName) {
            const decodedTopic = decodeURIComponent(topicName);
            pageTitle = `Topic: ${decodedTopic}`;
            articlesToDisplay = sourceArticles.filter(a => a.topic === decodedTopic || (a.tags && a.tags.includes(decodedTopic)));
            emptyMessage = `No articles found for topic "${decodedTopic}".`;
        } else if (pageType === 'search' && query) {
            pageTitle = `Search Results: "${query}"`;
            const tokens = query.toLowerCase().split(/[\s\W]+/).filter(Boolean);
            articlesToDisplay = sourceArticles
                .map(a => ({ ...a, score: calculateSearchScore(a, tokens) }))
                .filter(a => a.score > 0)
                .sort((a, b) => b.score - a.score); // Sort by relevance score
            emptyMessage = `No results found for "${query}".`;
        } else {
            pageTitle = "Page Not Found"; // Or handle other unknown page types
            emptyMessage = "Content not found.";
            articlesToDisplay = [];
        }

        titleElement.textContent = pageTitle;
        const siteName = document.title.split(' - ')[1] || 'Dacoola'; // Keep site name consistent
        document.title = `${pageTitle} - ${siteName}`;

        renderArticleCardList(container, articlesToDisplay, emptyMessage);

    } catch (error) {
        console.error(`Error loading data for generic page '${pageType}':`, error);
        titleElement.textContent = "Error";
        container.innerHTML = '<p class="placeholder error">Could not load content.</p>';
    }
}

/**
 * Loads and renders the "Latest News" section specifically for the 404 page.
 */
async function loadLatestNewsFor404() {
    const container = document.getElementById('page-content-area'); // Target the correct div in 404.html
    if (!container) {
        console.error("Latest news container (#page-content-area) not found on 404 page.");
        return;
    }
    container.innerHTML = '<p class="placeholder">Loading latest news...</p>';
    const allArticlesPath = '/all_articles.json'; // Path to your articles JSON

    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error fetching ${allArticlesPath}! Status: ${response.status}`);

        const allData = await response.json();
        if (!allData?.articles) throw new Error("Invalid all_articles.json format.");

        // Get a slice of the latest articles using the constant
        const latestArticles = allData.articles.slice(0, LATEST_NEWS_COUNT);

        // Use the existing function to render the cards
        renderArticleCardList(container, latestArticles, "No recent news available.");
        console.log("Rendered latest news section on 404 page.");

    } catch (error) {
        console.error('Error loading or rendering latest news on 404:', error);
        container.innerHTML = '<p class="placeholder error">Error loading latest news.</p>';
    }
}


/**
 * Loads sidebar data (Related & Latest) for the single article page.
 */
async function loadSidebarData() {
    const relatedContainer = document.getElementById('related-news-content');
    const latestContainer = document.getElementById('latest-news-content');
    const mainArticleElement = document.querySelector('.main-article');

    // Only proceed if we are on an article page with sidebars present
    if (!mainArticleElement || (!relatedContainer && !latestContainer)) {
        console.debug("Not an article page or sidebar containers missing.");
        return;
    }

    // Get context from the main article's data attributes
    let currentArticleId = mainArticleElement.getAttribute('data-article-id');
    let currentArticleTopic = mainArticleElement.getAttribute('data-article-topic');
    let currentArticleTags = [];
    try {
        const tagsJson = mainArticleElement.getAttribute('data-article-tags');
        if (tagsJson && tagsJson !== 'null' && tagsJson !== '[]') {
            currentArticleTags = JSON.parse(tagsJson);
            if (!Array.isArray(currentArticleTags)) currentArticleTags = [];
        }
    } catch (e) { console.error("Failed to parse tags for sidebar:", e); }

    console.log("Sidebar Context:", { id: currentArticleId, topic: currentArticleTopic, tags: currentArticleTags });

    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error fetching sidebar data. Status: ${response.status}`);
        const data = await response.json();
        if (!data?.articles) throw new Error(`Invalid JSON format in sidebar data`);

        const allArticles = data.articles;

        // Populate Latest News Sidebar
        if (latestContainer) {
            const latestSidebarArticles = allArticles
                .filter(a => a.id !== currentArticleId) // Exclude current article
                .slice(0, 5); // Show top 5 latest
            renderArticleCardList(latestContainer, latestSidebarArticles, "No recent news.");
            console.log(`Rendered latest news sidebar (${latestSidebarArticles.length} articles).`);
        }

        // Populate Related News Sidebar
        if (relatedContainer) {
            let relatedArticles = [];
            if (currentArticleId && (currentArticleTopic || currentArticleTags.length > 0)) {
                relatedArticles = allArticles
                    .filter(a => a.id !== currentArticleId) // Exclude current
                    .map(a => { // Score relevance
                        let score = 0;
                        if (a.topic === currentArticleTopic) score += 500;
                        const sharedTags = (a.tags || []).filter(t => currentArticleTags.includes(t)).length;
                        score += sharedTags * 50;
                        // Add recency bonus (less important than topic/tags)
                        if (a.published_iso) {
                           try { const ageFactor = Math.max(0, 1 - (new Date() - new Date(a.published_iso))/(1000*60*60*24*30)); score += ageFactor * 10; } catch {}
                        }
                        return { ...a, score };
                    })
                    .filter(a => a.score >= 10) // Basic threshold
                    .sort((a, b) => b.score - a.score) // Sort by score
                    .slice(0, 5); // Show top 5 related
            } else {
                // Fallback if no context: show latest excluding current
                relatedArticles = allArticles.filter(a => a.id !== currentArticleId).slice(0, 5);
                console.warn("Related news fallback: No topic/tags context provided by main article.");
            }
            renderArticleCardList(relatedContainer, relatedArticles, "No related news found.");
            console.log(`Rendered related news sidebar (${relatedArticles.length} articles).`);
        }
        // Timestamps updated globally

    } catch (err) {
        console.error('Error loading or processing sidebar data:', err);
        if (latestContainer) latestContainer.innerHTML = '<p class="placeholder error">Error loading latest</p>';
        if (relatedContainer) relatedContainer.innerHTML = '<p class="placeholder error">Error loading related</p>';
    }
}


// --- UI Rendering Functions ---

/**
 * Renders the breaking news/trending banner on the homepage.
 */
function renderBreakingNews(articles) {
    const section = document.getElementById('breaking-news-section');
    const container = document.getElementById('breaking-news-content');
    const titleElement = document.getElementById('breaking-news-title');
    if (!container || !titleElement || !section) return; // Ensure all elements exist

    container.innerHTML = ''; // Clear previous content
    if (autoSlideInterval) { clearInterval(autoSlideInterval); autoSlideInterval = null; } // Clear existing timer

    const now = new Date();
    // Filter for breaking news within the last 6 hours
    const breakingArticles = articles.filter(a =>
        a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6
    );

    let slidesData = [];
    let bannerTitle = "Breaking News";
    let labelText = "Breaking";
    let labelClass = "";
    const MAX_BANNER_SLIDES = 5;

    if (breakingArticles.length > 0) {
        slidesData = breakingArticles.slice(0, MAX_BANNER_SLIDES);
        bannerTitle = "Breaking News"; labelText = "Breaking"; labelClass = "";
    } else {
        // Fallback to trending if no recent breaking news
        const nonBreaking = articles
            .filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6))
            .sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0)); // Sort by trend score

        if (nonBreaking.length > 0) {
            slidesData = nonBreaking.slice(0, MAX_BANNER_SLIDES);
            bannerTitle = "Trending Now"; labelText = "Trending"; labelClass = "trending-label";
        } else {
            section.style.display = 'none'; // Hide section if nothing to show
            return;
        }
    }

    titleElement.textContent = bannerTitle;
    section.style.display = 'block'; // Ensure section is visible

    // Create slide elements
    slidesData.forEach((article, index) => {
        const linkPath = `/${article.link}`; // Assumes relative link from JSON
        const item = document.createElement('a');
        item.href = linkPath;
        item.className = `breaking-news-item slider-item ${index === 0 ? 'active' : ''}`; // First item is active
        item.innerHTML = `
            <span class="breaking-label ${labelClass}">${labelText}</span>
            <img src="${article.image_url || 'https://via.placeholder.com/1200x400?text=News'}" alt="${article.title || 'News image'}" loading="lazy">
            <div class="breaking-news-text">
                <h3>${article.title || 'Untitled'}</h3>
                <div class="breaking-news-meta">
                    <span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span>
                </div>
            </div>`;
        container.appendChild(item);
    });

    // Add slider controls and pagination if more than one slide
    const slides = container.querySelectorAll('.slider-item');
    if (slides.length > 1) {
        let currentSlideIndex = 0;
        const paginationContainer = document.createElement('div');
        paginationContainer.className = 'slider-pagination';

        const showSlide = (index) => {
            slides.forEach((slide, i) => slide.classList.toggle('active', i === index));
            paginationContainer.querySelectorAll('.slider-dot').forEach((dot, i) => dot.classList.toggle('active', i === index));
            currentSlideIndex = index;
        };
        const nextSlide = () => showSlide((currentSlideIndex + 1) % slides.length);
        const prevSlide = () => showSlide((currentSlideIndex - 1 + slides.length) % slides.length);

        // Create dots
        slides.forEach((_, index) => {
            const dot = document.createElement('button');
            dot.className = 'slider-dot';
            if (index === 0) dot.classList.add('active');
            dot.setAttribute('aria-label', `Go to slide ${index + 1}`);
            dot.addEventListener('click', () => showSlide(index));
            paginationContainer.appendChild(dot);
        });
        container.appendChild(paginationContainer);

        // Create Prev/Next buttons
        const prevButton = document.createElement('button');
        prevButton.className = 'slider-control slider-prev';
        prevButton.innerHTML = '<i class="fas fa-chevron-left"></i>';
        prevButton.title = "Previous";
        prevButton.addEventListener('click', (e) => { e.preventDefault(); prevSlide(); });
        container.appendChild(prevButton);

        const nextButton = document.createElement('button');
        nextButton.className = 'slider-control slider-next';
        nextButton.innerHTML = '<i class="fas fa-chevron-right"></i>';
        nextButton.title = "Next";
        nextButton.addEventListener('click', (e) => { e.preventDefault(); nextSlide(); });
        container.appendChild(nextButton);


        const AUTO_SLIDE_INTERVAL_MS = 5000;
        autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS);
        // Add mouseenter/mouseleave listeners to pause/resume auto-slide
        container.addEventListener('mouseenter', () => clearInterval(autoSlideInterval));
        container.addEventListener('mouseleave', () => {
            clearInterval(autoSlideInterval); // Clear just in case
            autoSlideInterval = setInterval(nextSlide, AUTO_SLIDE_INTERVAL_MS);
        });
    }
    // Timestamps updated globally
}

/**
 * Renders the main "Latest News" grid on the homepage.
 */
function renderLatestNewsGrid(articles) {
    const container = document.querySelector('#latest-news-section .latest-news-grid');
    if (!container) { console.error("Container for latest news grid not found."); return; }

    container.innerHTML = ''; // Clear previous
    const now = new Date();
    // Get IDs shown in banner to avoid duplication
    const breakingIdsInBanner = Array.from(document.querySelectorAll('#breaking-news-content a.breaking-news-item')).map(a => a.getAttribute('href'));

    // Filter out articles shown in banner or breaking news older than 6 hours
    const articlesForGrid = articles.filter(a => {
        const isOldBreaking = a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6;
        const isInBanner = breakingIdsInBanner.includes(`/${a.link}`);
        return (!a.is_breaking || isOldBreaking) && !isInBanner;
    });
    // Note: articles are already sorted newest first from the JSON file loading

    renderArticleCardList(container, articlesForGrid.slice(0, LATEST_NEWS_COUNT), "No recent news available.");
    console.log(`Rendered latest news grid (${articlesForGrid.slice(0, LATEST_NEWS_COUNT).length} articles).`);
}

/**
 * Renders the clickable topic buttons on the homepage.
 */
function renderTopics() {
    const container = document.querySelector('#topics-section .topics-list');
    if (!container) { console.error("Container for topics list not found."); return; }
    container.innerHTML = ''; // Clear previous

    // Keep this list synchronized with the Python ALLOWED_TOPICS list
     const predefinedTopics = [
        // Core AI/Tech
        "AI Models", "Hardware", "Software", "Robotics", "Compute",
        "Research", "Open Source",
        // Impact / Application
        "Business", "Startups", "Finance", "Health", "Society",
        "Ethics", "Regulation", "Art & Media", "Environment",
        "Education", "Security", "Gaming", "Transportation",
     ];

    if (predefinedTopics.length === 0) {
        container.innerHTML = '<p class="placeholder">No topics defined.</p>';
        return;
    }

    predefinedTopics.forEach(topic => {
        const button = document.createElement('a');
        button.href = `/topic.html?name=${encodeURIComponent(topic)}`; // Link to topic page
        button.className = 'topic-button';
        button.textContent = topic;
        container.appendChild(button);
    });
    console.log("Rendered topics section.");
}

/**
 * Renders the "Trending News" list on the homepage sidebar.
 */
function renderTrendingNews(articles) {
    const container = document.querySelector('#trending-news-section .trending-news-list');
    if (!container) { console.error("Container for trending news not found."); return; }
    container.innerHTML = ''; // Clear previous

    if (!articles || articles.length === 0) {
        container.innerHTML = '<p class="placeholder">No articles available.</p>';
        return;
    }

    // Sort by trend_score (highest first) and take top 4
    const sortedByTrend = articles.slice().sort((a, b) => (b.trend_score || 0) - (a.trend_score || 0));
    const articlesToShow = sortedByTrend.slice(0, 4);

    if (articlesToShow.length === 0) {
        container.innerHTML = '<p class="placeholder">No trending news found.</p>';
        return;
    }

    const ul = document.createElement('ul'); // Use UL for semantic list
    ul.className = 'trending-news-list-items'; // Add class if needed for styling
    articlesToShow.forEach(article => {
        const li = document.createElement('li');
        const linkPath = `/${article.link}`;
        li.innerHTML = `
            <a href="${linkPath}" class="sidebar-item-link">
                <div class="sidebar-item-image">
                    <img src="${article.image_url || 'https://via.placeholder.com/80x60?text=N/A'}" alt="${article.title || ''}" loading="lazy">
                </div>
                <div class="sidebar-item-content">
                    <h3 class="sidebar-item-title">${article.title || 'Untitled'}</h3>
                    <span class="sidebar-item-time timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span>
                </div>
            </a>`;
        ul.appendChild(li);
    });
    container.appendChild(ul);
    console.log("Rendered trending news list.");
    // Timestamps updated globally
}

/**
 * Renders a list of article cards into a specified container element.
 * Used by homepage, sidebars, generic pages, and 404 page.
 */
function renderArticleCardList(container, articles, emptyMessage) {
    if (!container) { console.error("Target container not found for article list render."); return; }
    container.innerHTML = ''; // Clear previous content

    if (!articles || articles.length === 0) {
        container.innerHTML = `<p class="placeholder">${emptyMessage}</p>`;
        return;
    }

    let renderCount = 0;
    articles.forEach(article => {
        // Basic validation of required article data
        if (!article?.id || !article?.title || !article?.link) {
            console.warn("Skipping render for invalid article data:", article);
            return;
        }
        renderCount++;

        const card = document.createElement('article');
        // Apply sidebar-specific class if the container is within a .sidebar element
        card.className = container.closest('.sidebar') ? 'article-card sidebar-card' : 'article-card';
        const linkPath = `/${article.link}`; // Assumes relative link from JSON
        const topic = article.topic || "News"; // Default topic
        const isBreaking = article.is_breaking || false;
        let showBreakingLabel = false;
        // Show breaking label only if flag is true and published within last 6 hours
        if (isBreaking && article.published_iso) {
            try { if ((new Date() - new Date(article.published_iso))/(1000*60*60) <= 6) showBreakingLabel = true; } catch {}
        }

        // Always include the browser TTS button structure
        const audioButtonHtml = `
            <button class="listen-button no-audio" title="Listen to article title (Browser TTS)" data-article-id="${article.id}">
                <i class="fas fa-headphones"></i>
            </button>`;

        card.innerHTML = `
            ${showBreakingLabel ? '<span class="breaking-label">Breaking</span>' : ''}
            <div class="article-card-actions">
                ${audioButtonHtml}
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

    console.log(`Rendered ${renderCount} article cards into container.`);
    // Listeners and timestamps are handled globally after initial page load
}


// --- Utility Functions ---

/**
 * Formats an ISO date string into a relative time string (e.g., "5 min ago").
 */
function timeAgo(isoDateString) {
    if (!isoDateString) return 'Date unknown';
    try {
        const date = new Date(isoDateString);
        if (isNaN(date)) return 'Invalid date'; // Check if date parsing failed

        const now = new Date();
        const seconds = Math.round((now - date) / 1000);

        if (seconds < 60) return `just now`;
        const minutes = Math.round(seconds / 60);
        if (minutes < 60) return `${minutes} min${minutes > 1 ? 's' : ''} ago`;
        const hours = Math.round(minutes / 60);
        if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
        const days = Math.round(hours / 24);
        if (days < 7) return `${days} day${days > 1 ? 's' : ''} ago`;
        const weeks = Math.round(days / 7);
        if (weeks < 5) return `${weeks} week${weeks > 1 ? 's' : ''} ago`;
        const months = Math.round(days / 30.44); // Average month length
        if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`;
        const years = Math.round(days / 365.25); // Account for leap years
        return `${years} year${years > 1 ? 's' : ''} ago`;
    } catch (e) {
        console.error("Date parse error:", isoDateString, e);
        return 'Date error';
    }
}

/**
 * Updates all elements with class 'timestamp' to show relative time.
 */
function updateTimestamps() {
    document.querySelectorAll('.timestamp').forEach(el => {
        const isoDate = el.getAttribute('data-iso-date');
        if (isoDate) {
            const formattedTime = timeAgo(isoDate);
            if (el.textContent !== formattedTime) {
                el.textContent = formattedTime;
                // Set tooltip to full date/time
                try { el.setAttribute('title', new Date(isoDate).toLocaleString()); }
                catch { el.setAttribute('title', 'Invalid date'); }
            }
        }
    });
}

/**
 * Calculates a simple relevance score for search results.
 */
function calculateSearchScore(article, searchTokens) {
    let score = 0;
    const title = article.title?.toLowerCase() || '';
    const topic = article.topic?.toLowerCase() || '';
    const tags = (article.tags || []).map(t => t.toLowerCase());
    const summary = article.summary_short?.toLowerCase() || '';
    const combinedText = `${title} ${topic} ${tags.join(' ')} ${summary}`;
    const combinedTokens = combinedText.split(/[\s\W]+/).filter(Boolean);
    const queryPhrase = searchTokens.join(' ');

    // Score based on token presence in different fields
    for (const token of searchTokens) {
        if (!token) continue;
        if (title.includes(token)) score += 15; // Higher weight for title
        if (topic.includes(token)) score += 8;
        if (tags.some(tag => tag.includes(token))) score += 5;
        if (summary.includes(token)) score += 2; // Lower weight for summary
    }

    // Bonus for matching the whole phrase
    if (title.includes(queryPhrase)) score += 50;
    else if (topic.includes(queryPhrase)) score += 25;
    else if (tags.some(tag => tag.includes(queryPhrase))) score += 15;
    else if (summary.includes(queryPhrase)) score += 10;

    // Bonus if all search tokens are present somewhere
    if (searchTokens.every(token => combinedTokens.includes(token))) {
        score += 20;
    }
    return score;
}

// --- Search Bar Functionality ---

/**
 * Sets up event listeners for the search input and suggestions dropdown.
 */
function setupSearch() {
    console.log("Setting up search functionality...");
    const searchInput = document.getElementById('search-input');
    const searchButton = document.getElementById('search-button');
    const suggestionsContainer = document.getElementById('search-suggestions');
    const searchContainer = document.querySelector('.nav-search'); // The div containing input/button

    if (!searchInput || !searchButton || !suggestionsContainer || !searchContainer) {
        console.warn("Search elements not found in the DOM, skipping search setup.");
        return;
    }

    searchContainer.style.position = 'relative'; // Needed for absolute positioning of suggestions
    let debounceTimeout;

    // Debounce function to limit API calls while typing
    function debounce(func, delay) {
        return (...args) => {
            clearTimeout(debounceTimeout);
            debounceTimeout = setTimeout(() => func.apply(this, args), delay);
        };
    }

    // Function to fetch and display search suggestions
    const showSuggestions = async (forceShow = false) => {
        const query = searchInput.value.trim().toLowerCase();
        suggestionsContainer.innerHTML = ''; // Clear previous suggestions
        suggestionsContainer.style.display = 'none'; // Hide by default

        // Only show if query has length or if forced (on focus)
        if (!forceShow && query.length < 1) return;

        const suggestDataPath = '/all_articles.json'; // Use the main data file
        try {
            const resp = await fetch(suggestDataPath, {cache: "no-store"});
            if (!resp.ok) throw new Error(`Suggestion fetch failed: ${resp.status}`);
            const data = await resp.json();
            if (!data?.articles) return; // No articles data

            let matches = [];
            // If query exists, filter and score
            if (query.length > 0) {
                const tokens = query.split(/[\s\W]+/).filter(Boolean);
                matches = data.articles
                    .map(a => ({...a, score: calculateSearchScore(a, tokens)}))
                    .filter(a => a.score > 0)
                    .sort((a, b) => b.score - a.score) // Sort by relevance
                    .slice(0, 5); // Limit to top 5 suggestions
            } else if (forceShow) {
                // On focus (forceShow), show the 5 most recent articles
                matches = data.articles.slice(0, 5);
            }

            if (matches.length > 0) {
                matches.forEach(a => {
                    const link = document.createElement('a');
                    link.href = `/${a.link}`; // Relative link to article page
                    link.className = 'suggestion-item';
                    link.innerHTML = `
                        <img src="${a.image_url || 'https://via.placeholder.com/80x50?text=N/A'}" class="suggestion-image" alt="" loading="lazy">
                        <div class="suggestion-text">
                            <span class="suggestion-title">${a.title}</span>
                            <span class="suggestion-meta timestamp" data-iso-date="${a.published_iso||''}">${timeAgo(a.published_iso)}</span>
                        </div>`;
                    suggestionsContainer.appendChild(link);
                });
                suggestionsContainer.style.display = 'block'; // Show dropdown
                updateTimestamps(); // Update relative times in suggestions
            }
        } catch (err) {
            console.error("Error fetching or processing suggestions:", err);
        }
    };

    // Function to redirect to the search results page
    const redirectSearch = () => {
        const query = searchInput.value.trim();
        if (query) {
            window.location.href = `/search.html?q=${encodeURIComponent(query)}`;
        } else {
            searchInput.focus(); // Keep focus if search is empty
        }
    };

    // Event Listeners
    searchButton.addEventListener('click', redirectSearch);
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault(); // Prevent default form submission
            redirectSearch();
        }
    });
    searchInput.addEventListener('input', debounce(showSuggestions, 300)); // Show suggestions after typing pause
    searchInput.addEventListener('focus', () => showSuggestions(true)); // Show recent on focus

    // Hide suggestions when clicking outside the search area
    document.addEventListener('click', (e) => {
        if (!searchContainer.contains(e.target)) {
            suggestionsContainer.style.display = 'none';
        }
    });
}


// --- Browser TTS Playback Logic ---

/**
 * Sets up delegated event listener for all TTS buttons on the page.
 */
function setupBrowserTTSListeners() {
    if (!synth) {
        console.warn("Browser speech synthesis not supported. TTS features disabled.");
        // Hide all TTS buttons if not supported
        document.querySelectorAll('.listen-button, #global-tts-player-button').forEach(btn => btn.style.display = 'none');
        return;
    }

    console.log("Setting up browser TTS event listeners...");
    // Use event delegation on the body for dynamically added cards
    document.body.removeEventListener('click', handleTTSDelegatedClick); // Remove previous listener if re-running
    document.body.addEventListener('click', handleTTSDelegatedClick);

    // Reset state of global button if it exists and isn't the currently playing one
    const globalButton = document.getElementById('global-tts-player-button');
    if (globalButton) {
        if (currentPlayingButton !== globalButton) {
            resetTTSButtonState(globalButton);
        } else if (synth.paused) { // If it IS the current one and it's paused
            globalButton.innerHTML = '<i class="fas fa-play"></i>'; // Show play icon
        }
    }

    // Ensure any card buttons marked as playing are reset if they aren't the active one
    document.querySelectorAll('.listen-button.playing').forEach(button => {
        if (button !== currentPlayingButton) {
            resetTTSButtonState(button);
        }
    });

    // Clean up speech synthesis on page unload
    window.removeEventListener('beforeunload', cancelSpeech);
    window.addEventListener('beforeunload', cancelSpeech);
}

/**
 * Handles clicks on TTS buttons using event delegation.
 */
function handleTTSDelegatedClick(event) {
    // Find the closest relevant button ancestor
    const button = event.target.closest('.listen-button, #global-tts-player-button');
    if (!button || !synth) return; // Click wasn't on a TTS button or synth not supported

    event.preventDefault(); // Prevent default link behavior if button is inside <a>
    event.stopPropagation(); // Stop event bubbling

    let textToSpeak = '';
    const isGlobalButton = button.id === 'global-tts-player-button';

    // Determine what text to speak based on the button clicked
    if (isGlobalButton) {
        const articleBody = document.getElementById('article-body');
        // Get text content, preferring innerText for better screen reader-like text
        textToSpeak = articleBody ? (articleBody.innerText || articleBody.textContent).trim() : '';
        if (!textToSpeak) {
             // Try getting title if body is empty (might be useful on list pages?)
             const headline = document.getElementById('article-headline');
             textToSpeak = headline ? (headline.innerText || headline.textContent).trim() : '';
        }
    } else { // It's a card's listen button
        const card = button.closest('.article-card');
        const titleElement = card?.querySelector('h3');
        textToSpeak = titleElement ? (titleElement.innerText || titleElement.textContent).trim() : '';
    }

    // --- Control Playback ---
    if (currentPlayingButton === button && currentUtterance) {
        // Clicked the button that is currently active
        if (synth.paused) {
            console.log("Attempting RESUME TTS.");
            button.innerHTML = '<i class="fas fa-pause"></i>'; // Show pause icon
            button.classList.remove('paused');
            synth.resume();
        } else if (synth.speaking) {
            console.log("Attempting PAUSE TTS.");
            button.innerHTML = '<i class="fas fa-play"></i>'; // Show play icon
            button.classList.add('paused');
            synth.pause();
        } else {
            // Synth isn't speaking or paused, but button is active? Reset state.
            console.log("Synth inactive but button was marked active. Resetting.");
            cancelSpeech(); // Reset everything
        }
    } else {
        // Clicked a new/inactive button, or no utterance active
        console.log("Clicked inactive/new button or no current speech. Starting new speech.");
        cancelSpeech(); // Stop any previous speech and reset buttons

        if (!textToSpeak) {
            console.warn("No text found for TTS.");
            alert("No content available to read aloud."); // User feedback
            resetTTSButtonState(button); // Reset the clicked button if no text
            return;
        }
        speakText(textToSpeak, button); // Start speaking the new text
    }
}

/**
 * Initiates speech synthesis for the given text and updates the button state.
 */
function speakText(text, button) {
    if (!synth || !text || !button) {
        console.error("speakText called with invalid arguments.", { textExists: !!text, buttonExists: !!button });
        if(button) resetTTSButtonState(button); // Try to reset if button exists
        return;
    }

    // Indicate loading state
    button.disabled = true;
    button.classList.remove('playing', 'paused'); // Clear previous states
    button.classList.add('loading');
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; // Loading spinner

    // Truncate very long text to avoid issues (limit varies by browser/voice)
    const MAX_TTS_CHARS = 3000;
    if (text.length > MAX_TTS_CHARS) {
        console.warn(`Text truncated to ${MAX_TTS_CHARS} characters for TTS.`);
        text = text.substring(0, MAX_TTS_CHARS - 3) + "...";
    }

    currentUtterance = new SpeechSynthesisUtterance(text);
    currentPlayingButton = button; // Associate this button with the speech

    // Event handlers for the utterance
    currentUtterance.onstart = () => {
        console.log("TTS started.");
        // Only update if this button is still the intended one
        if (currentPlayingButton === button) {
            button.classList.remove('loading');
            button.classList.add('playing');
            button.innerHTML = '<i class="fas fa-pause"></i>'; // Show pause icon
            button.disabled = false; // Enable pause/stop
        } else {
            console.log("TTS started, but target button changed before start.");
        }
    };

    currentUtterance.onpause = () => {
        console.log("TTS paused.");
        if (currentPlayingButton === button) {
            button.classList.add('paused');
            // Button remains enabled
        }
    };

    currentUtterance.onresume = () => {
        console.log("TTS resumed.");
        if (currentPlayingButton === button) {
            button.classList.remove('paused');
            button.classList.add('playing'); // Ensure playing class is back
            // Button remains enabled
        }
    };

    currentUtterance.onend = () => {
        console.log("TTS finished normally.");
        // Reset only if this was the button that finished
        if (currentPlayingButton === button) {
            resetTTSButtonState(button);
        } else {
             console.log("TTS ended, but not for the currently tracked button.");
        }
        // Nullify globals AFTER checking button match
        currentUtterance = null;
        currentPlayingButton = null;
    };

    currentUtterance.onerror = (e) => {
        console.error('TTS Error:', e);
        // Provide feedback for critical errors, ignore cancellations
        if (e.error && e.error !== 'interrupted' && e.error !== 'canceled') {
            alert(`Speech error: ${e.error}`);
        } else {
            console.log("TTS canceled or interrupted:", e.error || "Unknown reason");
        }
        // Reset the button associated with this failed/canceled utterance
        resetTTSButtonState(button);
        // Nullify globals if this was the active utterance
        if (currentPlayingButton === button) {
             currentUtterance = null;
             currentPlayingButton = null;
        }
    };

    // Start speaking
    synth.speak(currentUtterance);
}

/**
 * Resets a TTS button to its default state (headphones icon, not playing/loading).
 */
function resetTTSButtonState(button) {
    if (button) {
        button.classList.remove('playing', 'loading', 'paused');
        button.innerHTML = '<i class="fas fa-headphones"></i>';
        button.disabled = false;
    }
}

/**
 * Cancels any ongoing or pending speech synthesis.
 */
function cancelSpeech() {
    if (!synth) return;
    if (synth.speaking || synth.pending) {
        console.log("Cancelling/clearing active speech synthesis queue.");
        synth.cancel(); // Clears the queue and stops current speech
    }
    // Reset the button that *was* playing, if any
    if (currentPlayingButton) {
        resetTTSButtonState(currentPlayingButton);
    }
    // Clear global state tracking
    currentUtterance = null;
    currentPlayingButton = null;
}