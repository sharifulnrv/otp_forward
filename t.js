// ==UserScript==
// @name         SSLCommerz Auto-Mobile Provider & Pay
// @namespace    http://tampermonkey.net/
// @version      3.0
// @description  Selects Mobile Banking, provider, and clicks Pay button when ready
// @author       Gemini
// @match        *://*.sslcommerz.com/*
// @grant        none
// @allFrames    true
// ==/UserScript==

(function() {
    'use strict';

    // CONFIGURATION: Set your preferred provider here
    // Options: "Nagad", "bKash", "DBBL Mobile Banking", "upay", "Pocket"
    const targetProvider = "DBBL Mobile Banking";

    function automatePayment() {
        // 1. Ensure "Mobile Banking" tab is active
        const tabs = document.querySelectorAll('h1');
        tabs.forEach(h1 => {
            if (h1.textContent.includes('Mobile Banking')) {
                const card = h1.closest('.card');
                // Only click if it's not already active (checking background color class)
                if (card && !card.classList.contains('bg-[var(--data-color-primary)]')) {
                    card.click();
                }
            }
        });

        // 2. Look for and click the provider icon (bKash, Nagad, etc.)
        const providerImgs = document.querySelectorAll('img');
        providerImgs.forEach(img => {
            if (img.getAttribute('alt') === targetProvider) {
                const providerButton = img.closest('.relative');
                if (providerButton) {
                    // Check if already selected (usually has a specific border or tickIcon)
                    // If not selected, click it
                    providerButton.click();
                }
            }
        });

        // 3. Click the "Pay" button if it is NOT disabled
        const payBtn = document.querySelector('button[data-payment-button="true"]');
        if (payBtn) {
            const isDisabled = payBtn.getAttribute('aria-disabled') === 'true';
            const isBusy = payBtn.getAttribute('aria-busy') === 'true';

            if (!isDisabled && !isBusy) {
                console.log("Button is ready! Clicking Pay...");
                payBtn.click();

                // Once clicked, we can stop the interval
                clearInterval(autoRun);
            }
        }
    }

    // Run every 500ms to catch UI transitions
    const autoRun = setInterval(automatePayment, 500);

    // Safety timeout: Stop trying after 20 seconds
    setTimeout(() => clearInterval(autoRun), 20000);
})();