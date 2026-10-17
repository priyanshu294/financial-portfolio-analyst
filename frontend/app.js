const API_BASE = window.location.port === '3000' ? 'http://127.0.0.1:8000' : '';

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('analyzeForm');
    const btn = document.getElementById('submitBtn');
    
    // Sliders
    const maxVolSlider = document.getElementById('maxVolatility');
    const maxVolDisplay = document.getElementById('valVolatility');
    maxVolSlider.addEventListener('input', (e) => {
        maxVolDisplay.textContent = Number(e.target.value).toFixed(2);
    });

    const concLimitSlider = document.getElementById('concentrationLimit');
    const concLimitDisplay = document.getElementById('valConcentration');
    concLimitSlider.addEventListener('input', (e) => {
        concLimitDisplay.textContent = Number(e.target.value).toFixed(2);
    });

    // Preset Chips
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('preset-chip')) {
            document.getElementById('watchlist').value = e.target.getAttribute('data-tickers');
            document.getElementById('market').value = e.target.getAttribute('data-market');
            
            // Visual feedback
            const originalText = e.target.textContent;
            e.target.textContent = 'Loaded!';
            setTimeout(() => {
                e.target.textContent = originalText;
            }, 1000);
        }
    });

    // Submit handler
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const watchlistInput = document.getElementById('watchlist').value;
        const maxVol = parseFloat(maxVolSlider.value);
        const concLimit = parseFloat(concLimitSlider.value);
        const peThresh = parseFloat(document.getElementById('peThreshold').value);

        if (!watchlistInput.trim()) return;

        const watchlist = watchlistInput.split(',').map(s => s.trim().toUpperCase());

        const marketExchange = document.getElementById('market').value;

        const payload = {
            watchlist: watchlist,
            max_volatility: maxVol,
            concentration_limit: concLimit,
            pe_threshold: peThresh,
            market: marketExchange
        };

        // UI State: Loading
        btn.disabled = true;
        btn.textContent = "Analyzing...";
        document.getElementById('reportContainer').classList.add('hidden');
        document.getElementById('loadingState').classList.remove('hidden');
        
        const downloadBtn = document.getElementById('downloadBtn');
        if (downloadBtn) downloadBtn.classList.add('hidden');
        
        const feedbackContainer = document.getElementById('feedbackContainer');
        if (feedbackContainer) feedbackContainer.classList.add('hidden');

        let currentRunId = null;

        try {
            const response = await fetch(`${API_BASE}/api/analyze`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => null);
                const errMsg = errData && errData.detail ? errData.detail : `API Error: ${response.statusText}`;
                throw new Error(errMsg);
            }

            let currentMarkdown = "";
            let currentFilename = "Portfolio_Report.md";

            const data = await response.json();
            currentMarkdown = data.markdown;
            currentRunId = data.run_id;
            
            // Generate filename based on watchlist
            const dateStr = new Date().toISOString().split('T')[0];
            currentFilename = `Executive_Brief_${watchlist.join('_')}_${dateStr}.md`;
            
            // Render result
            const reportContainer = document.getElementById('reportContainer');
            reportContainer.innerHTML = data.html; // Inject HTML converted from markdown
            reportContainer.classList.remove('is-empty');
            
            // Inject SaaS Badges
            applyFintechStyles(reportContainer);

            // Show report, feedback bar, and download button
            document.getElementById('loadingState').classList.add('hidden');
            reportContainer.classList.remove('hidden');
            
            if (downloadBtn) downloadBtn.classList.remove('hidden');
            
            // Step 5: Activate LangSmith Feedback Widget
            if (feedbackContainer && currentRunId) {
                feedbackContainer.classList.remove('hidden');
                const thumbUpBtn = document.getElementById('thumbUpBtn');
                const thumbDownBtn = document.getElementById('thumbDownBtn');
                const feedbackStatus = document.getElementById('feedbackStatus');
                
                thumbUpBtn.className = 'feedback-btn';
                thumbDownBtn.className = 'feedback-btn';
                feedbackStatus.textContent = '';
                
                thumbUpBtn.onclick = () => {
                    thumbUpBtn.classList.add('active-positive');
                    thumbDownBtn.classList.remove('active-negative');
                    feedbackStatus.textContent = 'Thank you !';
                    
                    // Asynchronous background dispatch to LangSmith
                    fetch(`${API_BASE}/api/feedback`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            run_id: currentRunId,
                            key: 'user_satisfaction',
                            score: 1.0,
                            comment: 'User marked helpful'
                        })
                    }).catch(() => {});
                };
                
                thumbDownBtn.onclick = () => {
                    thumbDownBtn.classList.add('active-negative');
                    thumbUpBtn.classList.remove('active-positive');
                    feedbackStatus.textContent = 'Thank you !';
                    
                    // Asynchronous background dispatch to LangSmith
                    fetch(`${API_BASE}/api/feedback`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            run_id: currentRunId,
                            key: 'user_satisfaction',
                            score: 0.0,
                            comment: 'User marked unhelpful'
                        })
                    }).catch(() => {});
                };
            }
            
            // Bind download handler
            downloadBtn.onclick = async () => {
                downloadBtn.disabled = true;
                downloadBtn.innerHTML = "Generating Report...";
                
                try {
                    const pdfResponse = await fetch(`${API_BASE}/api/download-pdf`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            markdown: currentMarkdown,
                            filename: currentFilename.replace('.md', '.pdf'),
                            run_id: currentRunId
                        })
                    });
                    
                    if (!pdfResponse.ok) throw new Error("Failed to generate PDF");
                    
                    const blob = await pdfResponse.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = currentFilename.replace('.md', '.pdf');
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                } catch (e) {
                    alert("Error generating PDF: " + e.message);
                } finally {
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                    Download Report`;
                }
            };

        } catch (error) {
            document.getElementById('loadingState').classList.add('hidden');
            if (feedbackContainer) feedbackContainer.classList.add('hidden');
            const reportContainer = document.getElementById('reportContainer');
            
            let displayError = error.message;
            let title = "Analysis Interrupted";
            
            if (displayError.includes('Guardrail') || displayError.includes('Security') || displayError.includes('blocked') || displayError.includes('Invalid ticker')) {
                title = "Security & Guardrail Alert";
            } else if (displayError.includes('Internal Server Error') || displayError.includes('Failed to fetch')) {
                displayError = "Our financial data providers are currently experiencing high traffic. Please wait a moment and try again.";
            }

            reportContainer.innerHTML = `
                <div class="empty-state" style="color: var(--accent-red)">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 1.5rem; color: var(--accent-red);">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="12"></line>
                        <line x1="12" y1="16" x2="12.01" y2="16"></line>
                    </svg>
                    <h2>${title}</h2>
                    <p style="color: var(--text-secondary); max-width: 440px;">${displayError}</p>
                </div>
            `;
            reportContainer.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = "Generate Executive Brief";
        }
    });

    function applyFintechStyles(container) {
        // 1. Process List Items (Risk Score)
        const listItems = container.querySelectorAll('li');
        listItems.forEach(li => {
            if (li.textContent.includes('Risk Score:')) {
                const text = li.textContent;
                const scoreMatch = text.match(/(\d+)\s*\/\s*10/);
                if (scoreMatch) {
                    const score = parseInt(scoreMatch[1]);
                    let badgeClass = 'badge-low';
                    if (score >= 4 && score <= 6) badgeClass = 'badge-mod';
                    if (score >= 7) badgeClass = 'badge-high';
                    
                    li.innerHTML = `<strong>Risk Score:</strong> <span class="${badgeClass}">${score} / 10</span>`;
                }
            }
        });

        // 2. Process Table Action Verbs (Recommendation)
        const strongTags = container.querySelectorAll('table td strong');
        strongTags.forEach(tag => {
            const txt = tag.textContent.trim().toUpperCase();
            if (txt === 'INVESTIGATE' || txt === 'SELL') {
                tag.className = 'badge-high';
            } else if (txt === 'REVIEW' || txt === 'HOLD') {
                tag.className = 'badge-mod';
            } else {
                tag.className = 'badge-low';
            }
        });

        // 3. Process Table Risk Flag (Column 6)
        const tableRows = container.querySelectorAll('table tr');
        tableRows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length >= 6) {
                const riskCell = cells[5];
                const riskText = riskCell.textContent.trim();
                const lower = riskText.toLowerCase();
                let badgeClass = 'badge-low';
                let displayTxt = riskText;

                if (lower === 'none' || lower === 'null' || lower === 'n/a' || lower === '') {
                    displayTxt = 'Low Risk';
                    badgeClass = 'badge-low';
                } else if (lower.includes('high') || lower.includes('bearish') || lower.includes('negative') || lower.includes('alert')) {
                    badgeClass = 'badge-high';
                } else if (lower.includes('concentration') || lower.includes('momentum') || lower.includes('moderate') || lower.includes('review') || lower.includes('neutral')) {
                    badgeClass = 'badge-mod';
                } else {
                    badgeClass = 'badge-low';
                }

                riskCell.innerHTML = `<span class="${badgeClass}">${displayTxt}</span>`;
            }
        });
    }
});
