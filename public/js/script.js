// public/js/script.js (1/1) - FULL SCRIPT with highly refined slider click/drag and infinite loop

// --- Global Variables ---
const synth = window.speechSynthesis; 
let currentUtterance = null; 
let currentPlayingButton = null; 
let autoSlideInterval = null; 

const MAX_HOME_PAGE_ARTICLES = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--max-home-page-articles').trim() || '20', 10);
const LATEST_NEWS_GRID_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--latest-news-grid-count').trim() || '8', 10);
const TRENDING_NEWS_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--trending-news-count').trim() || '4', 10);
const SIDEBAR_DEFAULT_ITEM_COUNT = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-default-item-count').trim() || '5', 10);
const AVG_SIDEBAR_ITEM_HEIGHT_PX = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--avg-sidebar-item-height').trim() || '110', 10); 
const MAX_SIDEBAR_ITEMS = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--max-sidebar-items').trim() || '10', 10); 

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    loadNavbar().then(() => {
        setupSearch(); 
        setupMobileSearchToggle(); 
        initializePageContent(); 
        setupBrowserTTSListeners();
        setupFAQAccordion(); 
        setInterval(updateTimestamps, 60000);
        updateTimestamps();
    }).catch(error => console.error("CRITICAL: Failed to load navbar.", error));
});

function processArticleBodyFormatting() {
    const articleBody = document.getElementById('article-body');
    if (articleBody) {
        let content = articleBody.innerHTML;
        content = content.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        content = content.replace(/—/g, '-');
        articleBody.innerHTML = content;
    }
}

function initializePageContent() {
    const bodyClassList = document.body.classList;
    if (document.querySelector('.main-article')) { loadSidebarData(); processArticleBodyFormatting(); } 
    else if (document.querySelector('.home-container')) { loadHomepageData(); } 
    else if (bodyClassList.contains('page-404')) { loadLatestNewsFor404(); } 
    else if (document.querySelector('.page-container')) { loadGenericPageData(); }
}

async function loadNavbar() {
    const navbarPlaceholder = document.getElementById('navbar-placeholder');
    if (!navbarPlaceholder) {
        document.body.insertAdjacentHTML('afterbegin', '<p style="color:red;text-align:center;padding:5px;">Error: Navbar placeholder missing!</p>');
        return Promise.reject("Navbar placeholder missing");
    }
    try {
        const response = await fetch('/navbar.html', { cache: "no-store" });
        if (!response.ok) throw new Error(`Navbar fetch fail: ${response.status}`);
        const navbarHtml = await response.text();
        if (!navbarHtml || navbarHtml.trim().length < 20) throw new Error("Navbar HTML empty/invalid");
        navbarPlaceholder.innerHTML = navbarHtml;
        return navbarPlaceholder; 
    } catch (error) {
        navbarPlaceholder.innerHTML = '<p style="color:red;text-align:center;padding:10px;">Error loading navigation.</p>';
        return Promise.reject(error);
    }
}

async function loadHomepageData() {
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
        const allData = await response.json();
        if (!allData?.articles) throw new Error("Invalid all_articles.json format.");
        const allArticles = allData.articles;
        const bannerAndTrendingArticles = allArticles.slice(0, MAX_HOME_PAGE_ARTICLES); 
        renderBreakingNews(bannerAndTrendingArticles); 
        const bannerArticleLinks = Array.from(document.querySelectorAll('#breaking-news-content .slider-item')).map(a => a.getAttribute('href'));
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
        const errorMsg = '<p class="placeholder error">Error loading content.</p>';
        if (sel('#breaking-news-section .slider-track')) sel('#breaking-news-section .slider-track').innerHTML = errorMsg;
        else if (sel('#breaking-news-section .breaking-news-content')) sel('#breaking-news-section .breaking-news-content').innerHTML = errorMsg;
        if (sel('#latest-news-section .latest-news-grid')) sel('#latest-news-section .latest-news-grid').innerHTML = errorMsg;
        if (sel('#topics-section .topics-list')) sel('#topics-section .topics-list').innerHTML = errorMsg;
        if (sel('#trending-news-section .trending-news-list')) sel('#trending-news-section .trending-news-list').innerHTML = errorMsg;
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
        if (latestContainer) renderArticleCardList(latestContainer, [], "Loading news...");
        if (relatedContainer) renderArticleCardList(relatedContainer, [], "Loading related...");
        return;
    }
    if (!relatedContainer && !latestContainer) return;
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
    } catch (e) { console.warn("Could not calculate dynamic sidebar height, using default count.", e); }
    const allArticlesPath = '/all_articles.json';
    try {
        const response = await fetch(allArticlesPath, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
        const data = await response.json();
        if (!data?.articles) throw new Error(`Invalid JSON`);
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
                    if (a.published_iso) { try { score += Math.max(0, 1-(new Date()-new Date(a.published_iso))/(1000*60*60*24*30)) * 10; } catch {} }
                    return { ...a, score };
                })
                .filter(a => a.score >= 10).sort((a,b) => b.score - a.score).slice(0, numItemsForSidebarTarget); 
        }
        let finalItemCount = numItemsForSidebarTarget; 
        if (latestContainer && relatedContainer) finalItemCount = Math.min(numItemsForSidebarTarget, latestSidebarArticles_candidates.length, relatedArticles_candidates.length);
        else if (latestContainer) finalItemCount = Math.min(numItemsForSidebarTarget, latestSidebarArticles_candidates.length);
        else if (relatedContainer) finalItemCount = Math.min(numItemsForSidebarTarget, relatedArticles_candidates.length);
        if (latestContainer) renderArticleCardList(latestContainer, latestSidebarArticles_candidates.slice(0, finalItemCount), "No recent news.");
        if (relatedContainer) renderArticleCardList(relatedContainer, relatedArticles_candidates.slice(0, finalItemCount), "No related news.");
    } catch (err) {
        console.error('Error loading sidebar data:', err);
        if (latestContainer) latestContainer.innerHTML = '<p class="placeholder error">Error loading latest</p>';
        if (relatedContainer) relatedContainer.innerHTML = '<p class="placeholder error">Error loading related</p>';
    }
}

function renderBreakingNews(articles) {
    const section = document.getElementById('breaking-news-section');
    const sliderContainer = document.getElementById('breaking-news-content');
    const titleElement = document.getElementById('breaking-news-title');

    if (!sliderContainer || !titleElement || !section) {
        if (section) section.style.display = 'none'; return;
    }
    
    const sliderTrack = sliderContainer.querySelector('.slider-track');
    if (!sliderTrack) {
        console.error("Slider track not found!"); 
        if (section) section.style.display = 'none'; return;
    }

    sliderTrack.innerHTML = ''; 
    if (autoSlideInterval) clearInterval(autoSlideInterval);
    
    const now = new Date();
    const breakingArticles = articles.filter(a => a.is_breaking && a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) <= 6);
    let slidesData = [], bannerTitle = "Breaking News", labelText = "Breaking", labelClass = "";
    const MAX_BANNER_SLIDES = 5;

    if (breakingArticles.length > 0) { slidesData = breakingArticles.slice(0, MAX_BANNER_SLIDES); } 
    else {
        const nonBreaking = articles.filter(a => !a.is_breaking || (a.published_iso && (now - new Date(a.published_iso))/(1000*60*60) > 6))
            .sort((a,b) => (b.trend_score || 0) - (a.trend_score || 0));
        if (nonBreaking.length > 0) { slidesData = nonBreaking.slice(0, MAX_BANNER_SLIDES); bannerTitle = "Trending Now"; labelText = "Trending"; labelClass = "trending-label"; } 
        else { section.style.display = 'none'; return; }
    }

    titleElement.textContent = bannerTitle;
    section.style.display = 'block'; 

    if (slidesData.length === 0) { 
        sliderTrack.innerHTML = '<p class="placeholder">No banner news available.</p>';
        return;
    }
    
    let effectiveSlidesData = [...slidesData];
    const needsCloning = slidesData.length > 1;
    if (needsCloning) {
        effectiveSlidesData.unshift(slidesData[slidesData.length - 1]); 
        effectiveSlidesData.push(slidesData[0]); 
    }

    effectiveSlidesData.forEach(article => {
        const linkPath = `/${article.link}`; 
        const item = document.createElement('a'); 
        item.href = linkPath;
        item.className = 'breaking-news-item slider-item';
        item.draggable = false; 
        item.innerHTML = `
            <span class="breaking-label ${labelClass}">${labelText}</span>
            <img src="${article.image_url || 'https://via.placeholder.com/1200x400?text=News'}" alt="${article.title || 'News image'}" loading="lazy" draggable="false">
            <div class="breaking-news-text"><h3>${article.title || 'Untitled'}</h3><div class="breaking-news-meta"><span class="timestamp" data-iso-date="${article.published_iso || ''}">${timeAgo(article.published_iso)}</span></div></div>`;
        sliderTrack.appendChild(item);
    });

    sliderContainer.querySelectorAll('.slider-control, .slider-pagination').forEach(el => el.remove());

    if (slidesData.length > 0) {
        let currentLogicalIndex = 0; 
        let currentDisplayIndex = needsCloning ? 1 : 0; 
        const totalOriginalSlides = slidesData.length;
        let slideWidth = sliderContainer.offsetWidth; 

        const paginationContainer = document.createElement('div');
        paginationContainer.className = 'slider-pagination';

        const updateSlidePosition = (animate = true) => {
            slideWidth = sliderContainer.offsetWidth; 
            const offset = -currentDisplayIndex * slideWidth;
            sliderTrack.style.transition = animate ? 'transform 0.4s ease-in-out' : 'none';
            sliderTrack.style.transform = `translateX(${offset}px)`;
            
            if (totalOriginalSlides > 1) {
                paginationContainer.querySelectorAll('.slider-dot').forEach((dot, i) => {
                    dot.classList.toggle('active', i === currentLogicalIndex);
                });
            }
        };
        
        const handleTransitionEnd = () => {
            sliderTrack.removeEventListener('transitionend', handleTransitionEnd);
            if (currentDisplayIndex === 0 && needsCloning) { 
                currentDisplayIndex = totalOriginalSlides; 
                currentLogicalIndex = totalOriginalSlides -1;
                updateSlidePosition(false); 
            } else if (currentDisplayIndex === (effectiveSlidesData.length -1) && needsCloning) { // Check against effectiveSlidesData length for last clone
                currentDisplayIndex = 1; 
                currentLogicalIndex = 0;
                updateSlidePosition(false);
            }
        };

        const changeSlide = (direction) => {
            currentLogicalIndex = (currentLogicalIndex + direction + totalOriginalSlides) % totalOriginalSlides;
            if (needsCloning) {
                currentDisplayIndex += direction;
                 sliderTrack.addEventListener('transitionend', handleTransitionEnd);
            } else {
                currentDisplayIndex = currentLogicalIndex;
            }
            updateSlidePosition(true);
            resetAutoSlide();
        };
        
        const nextSlide = () => changeSlide(1);
        const prevSlide = () => changeSlide(-1);

        const goToSlide = (originalIndex) => { 
            currentLogicalIndex = originalIndex;
            currentDisplayIndex = needsCloning ? originalIndex + 1 : originalIndex;
            updateSlidePosition(true); 
            resetAutoSlide(); 
            if (needsCloning) sliderTrack.addEventListener('transitionend', handleTransitionEnd);
        };
        const resetAutoSlide = () => { clearInterval(autoSlideInterval); if(totalOriginalSlides > 1) autoSlideInterval = setInterval(nextSlide, 7000); };

        if (totalOriginalSlides > 1) {
            for (let i = 0; i < totalOriginalSlides; i++) {
                const dot = document.createElement('button'); dot.className = 'slider-dot';
                dot.setAttribute('aria-label', `Go to slide ${i + 1}`);
                dot.addEventListener('click', (e) => { e.stopPropagation(); goToSlide(i); });
                paginationContainer.appendChild(dot);
            }
            sliderContainer.appendChild(paginationContainer);

            const prevButton = document.createElement('button'); prevButton.className = 'slider-control slider-prev'; prevButton.innerHTML = '<i class="fas fa-chevron-left"></i>'; prevButton.title="Previous";
            prevButton.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); prevSlide(); });
            sliderContainer.appendChild(prevButton);

            const nextButton = document.createElement('button'); nextButton.className = 'slider-control slider-next'; nextButton.innerHTML = '<i class="fas fa-chevron-right"></i>'; nextButton.title="Next";
            nextButton.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); nextSlide(); });
            sliderContainer.appendChild(nextButton);
        }
        
        autoSlideInterval = setInterval(nextSlide, 7000);
        sliderContainer.addEventListener('mouseenter', () => clearInterval(autoSlideInterval));
        sliderContainer.addEventListener('mouseleave', resetAutoSlide);

        let pointerDownX = 0;
        let currentTrackPixelOffset = 0; 
        let pointerIsDown = false;
        let downTimestamp = 0;
        let hasDraggedSignificantly = false; 
        const DRAG_START_THRESHOLD = 5; // Minimal movement to initiate drag state
        const SWIPE_ACTION_THRESHOLD_PIXELS = 50; 
        const CLICK_TIME_THRESHOLD_MS = 250; // Reduced time for a more responsive click

        sliderContainer.addEventListener('pointerdown', (e) => {
            if (e.button !== 0) return; // Only primary button (left-click or touch)
            if (e.target.closest('.slider-control, .slider-pagination')) return;
            
            pointerDownX = e.clientX;
            downTimestamp = e.timeStamp;
            hasDraggedSignificantly = false;
            pointerIsDown = true;
            
            sliderContainer.classList.add('dragging');
            sliderTrack.style.transition = 'none'; 
            slideWidth = sliderContainer.offsetWidth; 
            currentTrackPixelOffset = -currentDisplayIndex * slideWidth; 
            
            clearInterval(autoSlideInterval);
            e.preventDefault(); 
        }, { passive: false });

        sliderContainer.addEventListener('pointermove', (e) => {
            if (!pointerIsDown) return;
            const dragDeltaX = e.clientX - pointerDownX;
            if (!hasDraggedSignificantly && Math.abs(dragDeltaX) > DRAG_START_THRESHOLD) { 
                hasDraggedSignificantly = true;
            }
            sliderTrack.style.transform = `translateX(${currentTrackPixelOffset + dragDeltaX}px)`;
        });

        const handlePointerRelease = (e) => {
            if (!pointerIsDown) return;
            
            const wasDraggingClassApplied = sliderContainer.classList.contains('dragging');
            sliderContainer.classList.remove('dragging');
            pointerIsDown = false; // Reset flag immediately
            
            const dragDeltaX = e.clientX - pointerDownX;
            const timeElapsed = e.timeStamp - downTimestamp;
            
            if (e.target.closest('.slider-control, .slider-pagination')) {
                 resetAutoSlide(); 
                 return;
            }

            // Strict Click Condition: No significant drag, short time, primary button, AND target is the slide link
            if (!hasDraggedSignificantly && timeElapsed < CLICK_TIME_THRESHOLD_MS && e.button === 0) {
                const targetSlideElement = e.target.closest('a.slider-item');
                if (targetSlideElement && targetSlideElement.href) {
                    // Check if the click was not on a control button (already done, but good to be sure)
                    if (!e.target.closest('.slider-control')) {
                        window.location.href = targetSlideElement.href;
                        // No resetAutoSlide() here as we are navigating away.
                        return; 
                    }
                }
                // If not a direct link click, or conditions not fully met, treat as snap back
                updateSlidePosition(true);
            } else if (Math.abs(dragDeltaX) >= SWIPE_ACTION_THRESHOLD_PIXELS) { 
                if (dragDeltaX < 0) { changeSlide(1); } 
                else { changeSlide(-1); } 
            } else { 
                updateSlidePosition(true); // Snap back if not enough drag for swipe and not a click
            }
            resetAutoSlide();
        };

        sliderContainer.addEventListener('pointerup', handlePointerRelease);
        // For robustness, handle cases where pointer leaves the element while still pressed
        sliderContainer.addEventListener('pointerleave', (e) => { if(pointerIsDown) handlePointerRelease(e);});
        sliderContainer.addEventListener('pointercancel', (e) => { if(pointerIsDown) handlePointerRelease(e);});
        
        window.addEventListener('resize', () => {
            updateSlidePosition(false); 
        });
        updateSlidePosition(false); 
    } else if (slidesData.length === 1) {
        sliderTrack.style.transform = 'translateX(0px)';
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

function timeAgo(isoDateString) {
    if (!isoDateString) return 'Date unknown'; 
    try { 
        const date = new Date(isoDateString); 
        if (isNaN(date)) return 'Invalid date'; 
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
        const months = Math.round(days / 30.44); 
        if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`; 
        const years = Math.round(days / 365.25); 
        return `${years} year${years > 1 ? 's' : ''} ago`; 
    } catch (e) { 
        console.error("Date parse error:", isoDateString, e); 
        return 'Date error'; 
    }
}

function updateTimestamps() {
    document.querySelectorAll('.timestamp').forEach(el => { 
        const isoDate = el.getAttribute('data-iso-date'); 
        if (isoDate) { 
            const formattedTime = timeAgo(isoDate); 
            if (el.textContent !== formattedTime) { 
                el.textContent = formattedTime; 
                try { 
                    el.setAttribute('title', new Date(isoDate).toLocaleString()); 
                } catch { 
                    el.setAttribute('title', 'Invalid date'); 
                } 
            } 
        } 
    });
}

function calculateSearchScore(article, searchTokens) {
    let score = 0; 
    const title = article.title?.toLowerCase() || ''; 
    const topic = article.topic?.toLowerCase() || ''; 
    const tags = (article.tags || []).map(t => t.toLowerCase()); 
    const summary = article.summary_short?.toLowerCase() || ''; 
    const text = `${title} ${topic} ${tags.join(' ')} ${summary}`; 
    const textTokens = text.split(/[\s\W]+/).filter(Boolean); 
    const qPhrase = searchTokens.join(' ');
    for (const token of searchTokens) { 
        if (!token) continue; 
        if (title.includes(token)) score += 15; 
        if (topic.includes(token)) score += 8; 
        if (tags.some(tag => tag.includes(token))) score += 5; 
        if (summary.includes(token)) score += 2; 
    }
    if (title.includes(qPhrase)) score += 50; 
    else if (topic.includes(qPhrase)) score += 25; 
    else if (tags.some(tag => tag.includes(qPhrase))) score += 15; 
    else if (summary.includes(qPhrase)) score += 10;
    if (searchTokens.every(token => textTokens.includes(token))) score += 20; 
    return score;
}

function setupSearch() {
    const searchInput = document.getElementById('search-input');
    const searchButton = document.getElementById('search-button');
    const suggestionsContainer = document.getElementById('search-suggestions');
    const searchContainer = document.querySelector('.nav-search'); 
    if (!searchInput || !searchButton || !suggestionsContainer || !searchContainer) {
        console.warn("Standard desktop search elements missing."); return;
    }
    searchContainer.style.position = 'relative'; 
    let debounceTimeout;
    const debounce = (func, delay) => (...args) => {
        clearTimeout(debounceTimeout);
        debounceTimeout = setTimeout(() => func.apply(this, args), delay);
    };
    const showSuggestions = async (forceShow = false) => {
        const query = searchInput.value.trim().toLowerCase();
        suggestionsContainer.innerHTML = '';
        suggestionsContainer.style.display = 'none';
        if (!forceShow && query.length < 1) return;
        try {
            const resp = await fetch('/all_articles.json', { cache: "no-store" });
            if (!resp.ok) throw new Error("Fetch fail");
            const data = await resp.json();
            if (!data?.articles) return;
            let matches = [];
            if (query.length > 0) {
                const tokens = query.split(/[\s\W]+/).filter(Boolean);
                matches = data.articles.map(a => ({ ...a, score: calculateSearchScore(a, tokens) }))
                                      .filter(a => a.score > 0).sort((a,b) => b.score - a.score).slice(0, 5); 
            } else if (forceShow) { matches = data.articles.slice(0, 5); }
            if (matches.length > 0) {
                matches.forEach(a => {
                    const link = document.createElement('a'); link.href = `/${a.link}`; link.className = 'suggestion-item';
                    link.innerHTML = `<img src="${a.image_url || 'https://via.placeholder.com/80x50?text=N/A'}" class="suggestion-image" alt="" loading="lazy"><div class="suggestion-text"><span class="suggestion-title">${a.title}</span><span class="suggestion-meta timestamp" data-iso-date="${a.published_iso || ''}">${timeAgo(a.published_iso)}</span></div>`;
                    suggestionsContainer.appendChild(link);
                });
                suggestionsContainer.style.display = 'block'; updateTimestamps(); 
            }
        } catch (err) { console.error("Suggest err:", err); }
    };
    const redirectSearch = () => {
        const q = searchInput.value.trim();
        if (q) window.location.href = `/search.html?q=${encodeURIComponent(q)}`;
        else searchInput.focus(); 
    };
    searchButton.addEventListener('click', redirectSearch);
    searchInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); redirectSearch(); } });
    searchInput.addEventListener('input', debounce(showSuggestions, 300));
    searchInput.addEventListener('focus', () => showSuggestions(true)); 
    document.addEventListener('click', (e) => {
        if (!searchContainer.contains(e.target) && !e.target.closest('#mobile-search-toggle')) {
            suggestionsContainer.style.display = 'none';
        }
    });
}

function setupMobileSearchToggle() {
    const toggleButton = document.getElementById('mobile-search-toggle');
    const navbar = document.querySelector('.navbar');
    const searchContainer = document.querySelector('.nav-search'); 
    if (!toggleButton || !navbar || !searchContainer) {
         console.warn("Mobile search toggle elements not found."); return;
    }
    toggleButton.addEventListener('click', (e) => {
        e.stopPropagation(); 
        navbar.classList.toggle('search-active'); 
        searchContainer.classList.toggle('mobile-active'); 
        if (searchContainer.classList.contains('mobile-active')) {
            const searchInput = document.getElementById('search-input');
            if (searchInput) searchInput.focus();
        } else {
            const suggestions = document.getElementById('search-suggestions');
            if (suggestions) suggestions.style.display = 'none';
        }
    });
     document.addEventListener('click', (e) => {
         if (navbar.classList.contains('search-active') &&
             !searchContainer.contains(e.target) && 
             !toggleButton.contains(e.target)) {    
             navbar.classList.remove('search-active');
             searchContainer.classList.remove('mobile-active');
             const suggestions = document.getElementById('search-suggestions');
             if (suggestions) suggestions.style.display = 'none'; 
         }
     });
}

function setupFAQAccordion() {
    const faqSections = document.querySelectorAll('#article-body .faq-section');
    faqSections.forEach(faqSection => {
        const faqItems = faqSection.querySelectorAll('details.faq-item');
        if (faqItems.length > 0) { /* No specific JS needed for native <details> */ }
    });
}

function setupBrowserTTSListeners() {
    if (!synth) { 
        console.warn("Browser TTS not supported."); 
        document.querySelectorAll('.listen-button, #global-tts-player-button').forEach(btn => btn.style.display = 'none'); 
        return; 
    }
    document.body.removeEventListener('click', handleTTSDelegatedClick); 
    document.body.addEventListener('click', handleTTSDelegatedClick);
    const globalButton = document.getElementById('global-tts-player-button');
    if (globalButton) {
        globalButton.setAttribute('aria-label', 'Listen to main article content');
        if (currentPlayingButton !== globalButton) { resetTTSButtonState(globalButton); } 
        else if (synth.paused) { globalButton.innerHTML = '<i class="fas fa-play" aria-hidden="true"></i>'; }
    }
    document.querySelectorAll('.listen-button.playing').forEach(button => {
        if (button !== currentPlayingButton) resetTTSButtonState(button);
    });
    window.addEventListener('beforeunload', cancelSpeech); 
}

function handleTTSDelegatedClick(event) {
    const button = event.target.closest('.listen-button, #global-tts-player-button');
    if (!button || !synth) return; 
    event.preventDefault(); event.stopPropagation(); 
    let textToSpeak = '';
    const isGlobalButton = button.id === 'global-tts-player-button';
    if (isGlobalButton) {
        const articleBody = document.getElementById('article-body');
        textToSpeak = articleBody ? (articleBody.innerText || articleBody.textContent).trim() : '';
        if(!textToSpeak){ 
            const headline = document.getElementById('article-headline');
            textToSpeak = headline ? (headline.innerText || headline.textContent).trim() : '';
        }
    } else { 
        const card = button.closest('.article-card');
        const titleElement = card?.querySelector('h3');
        textToSpeak = titleElement ? (titleElement.innerText || titleElement.textContent).trim() : '';
    }
    if (currentPlayingButton === button && currentUtterance) { 
        if (synth.paused) { 
            button.innerHTML = '<i class="fas fa-pause" aria-hidden="true"></i>'; 
            button.setAttribute('aria-label', 'Pause audio narration');
            button.classList.remove('paused'); synth.resume(); 
        }
        else if (synth.speaking) { 
            button.innerHTML = '<i class="fas fa-play" aria-hidden="true"></i>'; 
            button.setAttribute('aria-label', 'Resume audio narration');
            button.classList.add('paused'); synth.pause(); 
        }
        else { cancelSpeech(); }
    } else { 
        cancelSpeech(); 
        if (!textToSpeak) { 
            console.warn("No text for TTS."); alert("No content to read for this item."); 
            resetTTSButtonState(button); return; 
        }
        speakText(textToSpeak, button);
    }
}

function speakText(text, button) {
    if (!synth || !text || !button) { if(button) resetTTSButtonState(button); return; }
    button.disabled = true; button.classList.remove('playing', 'paused'); button.classList.add('loading');
    button.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i>'; 
    button.setAttribute('aria-label', 'Loading audio narration');
    const MAX_TTS_CHARS = 3000; 
    if (text.length > MAX_TTS_CHARS) { text = text.substring(0, MAX_TTS_CHARS - 3) + "..."; }
    currentUtterance = new SpeechSynthesisUtterance(text); currentPlayingButton = button;
    currentUtterance.onstart = () => {
        if (currentPlayingButton === button) { 
            button.classList.remove('loading'); button.classList.add('playing');
            button.innerHTML = '<i class="fas fa-pause" aria-hidden="true"></i>';
            button.setAttribute('aria-label', 'Pause audio narration'); button.disabled = false;
        }
    };
    currentUtterance.onpause = () => { if (currentPlayingButton === button) button.classList.add('paused'); };
    currentUtterance.onresume = () => { if (currentPlayingButton === button) { button.classList.remove('paused'); button.classList.add('playing'); }};
    currentUtterance.onend = () => {
        if (currentPlayingButton === button) resetTTSButtonState(button); 
        currentUtterance = null; currentPlayingButton = null; 
    };
    currentUtterance.onerror = (e) => {
        console.error('TTS Error:', e);
        if (e.error && e.error !== 'interrupted' && e.error !== 'canceled') { alert(`Speech error: ${e.error}`); }
        resetTTSButtonState(button); 
        if (currentPlayingButton === button) { currentUtterance = null; currentPlayingButton = null; }
    };
    synth.speak(currentUtterance);
}

function resetTTSButtonState(button) {
    if (button) {
        button.classList.remove('playing', 'loading', 'paused');
        const iconClass = button.id === 'global-tts-player-button' ? 'fa-headphones' : 'fa-headphones';
        button.innerHTML = `<i class="fas ${iconClass}" aria-hidden="true"></i>`;
        button.disabled = false;
        const defaultListenLabel = button.id === 'global-tts-player-button' ? 'Listen to main article content' : 'Listen to article title';
        button.setAttribute('aria-label', defaultListenLabel);
    }
}

function cancelSpeech() {
    if (!synth) return;
    if (synth.speaking || synth.pending) { synth.cancel(); }
    if (currentPlayingButton) { resetTTSButtonState(currentPlayingButton); }
    currentUtterance = null; currentPlayingButton = null;
}