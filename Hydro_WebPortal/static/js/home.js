// Homepage JavaScript Functionality

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all homepage features
    initMobileNavigation();
    initSmoothScrolling();
    initAnimations();
    initFeatureCards();
    initTypingEffect();
    initCounterAnimations();
});

// Mobile Navigation
function initMobileNavigation() {
    const hamburger = document.querySelector('.hamburger');
    const navMenu = document.querySelector('.nav-menu');
    const navLinks = document.querySelectorAll('.nav-link');

    if (hamburger && navMenu) {
        hamburger.addEventListener('click', function() {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });

        // Close mobile menu when clicking on a link
        navLinks.forEach(link => {
            link.addEventListener('click', function() {
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            });
        });

        // Close mobile menu when clicking outside
        document.addEventListener('click', function(e) {
            if (!hamburger.contains(e.target) && !navMenu.contains(e.target)) {
                hamburger.classList.remove('active');
                navMenu.classList.remove('active');
            }
        });
    }
}

// Smooth Scrolling for Navigation Links
function initSmoothScrolling() {
    const navLinks = document.querySelectorAll('a[href^="#"]');
    
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            const targetSection = document.querySelector(targetId);
            
            if (targetSection) {
                const headerHeight = document.querySelector('.navbar').offsetHeight;
                const targetPosition = targetSection.offsetTop - headerHeight;
                
                window.scrollTo({
                    top: targetPosition,
                    behavior: 'smooth'
                });
            }
        });
    });
}

// Scroll Animations (modified to exclude features section)
function initAnimations() {
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                // Don't add animation to features section elements
                if (!entry.target.closest('.features')) {
                    entry.target.classList.add('animate-in');
                }
                
                // Trigger counter animations when stats section comes into view
                if (entry.target.classList.contains('stats-container')) {
                    animateCounters();
                }
            }
        });
    }, observerOptions);

    // Observe all animatable elements except those in features section
    const animateElements = document.querySelectorAll('.about-content, .stat-card, .section-header');
    animateElements.forEach(el => {
        observer.observe(el);
    });
    
    // For feature cards, add them to the page without animation
    const featureCards = document.querySelectorAll('.feature-card');
    featureCards.forEach(card => {
        card.style.opacity = '1';
        card.style.transform = 'none';
    });
}

// Feature Cards Interaction (hover effects only, no scroll animations)
function initFeatureCards() {
    const featureCards = document.querySelectorAll('.feature-card');
    
    featureCards.forEach(card => {
        // Ensure cards start with no transform
        card.style.transform = 'none';
        
        // Add hover effects (but don't move up/down)
        card.addEventListener('mouseenter', function() {
            this.style.boxShadow = '0 15px 30px rgba(0,0,0,0.2)';
            this.style.borderColor = '#3498db';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.boxShadow = '0 10px 30px rgba(0,0,0,0.1)';
            this.style.borderColor = 'transparent';
            this.style.transform = 'none';
        });

        // Handle clicks for navigation (without movement)
        card.addEventListener('click', function() {
            const onclick = this.getAttribute('onclick');
            if (onclick) {
                // Just slightly change appearance without moving
                this.style.opacity = '0.9';
                setTimeout(() => {
                    this.style.opacity = '1';
                    eval(onclick);
                }, 150);
            }
        });
    });
}

// Typing Effect for Hero Section
function initTypingEffect() {
    const heroTitle = document.querySelector('.hero-text h1');
    if (!heroTitle) return;

    const text = heroTitle.textContent;
    heroTitle.textContent = '';
    
    // Add cursor element
    const cursor = document.createElement('span');
    cursor.className = 'typing-cursor';
    cursor.textContent = '|';
    heroTitle.appendChild(cursor);
    
    let index = 0;
    const typeSpeed = 100;
    
    function typeText() {
        if (index < text.length) {
            const currentText = text.slice(0, index + 1);
            heroTitle.innerHTML = currentText + '<span class="typing-cursor">|</span>';
            index++;
            setTimeout(typeText, typeSpeed);
        } else {
            // Remove cursor after typing is complete
            setTimeout(() => {
                const cursor = heroTitle.querySelector('.typing-cursor');
                if (cursor) cursor.remove();
            }, 1000);
        }
    }
    
    // Start typing after a delay
    setTimeout(typeText, 500);
}

// Counter Animations
function initCounterAnimations() {
    const counters = document.querySelectorAll('.stat-number, .stat .number');
    
    counters.forEach(counter => {
        const target = parseFloat(counter.textContent.replace(/[^\d.]/g, ''));
        const suffix = counter.textContent.replace(/[\d.]/g, '');
        let current = 0;
        const increment = target / 50;
        const duration = 2000;
        const stepTime = duration / 50;
        
        counter.textContent = '0' + suffix;
        
        function updateCounter() {
            current += increment;
            if (current < target) {
                counter.textContent = Math.floor(current) + suffix;
                setTimeout(updateCounter, stepTime);
            } else {
                counter.textContent = target + suffix;
            }
        }
        
        // Store the animation function for later use
        counter.animateCounter = updateCounter;
    });
}

// Animate counters when they come into view
function animateCounters() {
    const counters = document.querySelectorAll('.stat-number, .stat .number');
    counters.forEach(counter => {
        if (counter.animateCounter) {
            counter.animateCounter();
        }
    });
}

// Navigation Functions
function navigateToDelineation() {
    // Add loading animation
    const body = document.body;
    body.style.opacity = '0.8';
    body.style.transition = 'opacity 0.3s ease';
    
    // Navigate to delineation tool
    setTimeout(() => {
        window.location.href = '/delineation/';
    }, 300);
}

function scrollToFeatures() {
    const featuresSection = document.querySelector('#features');
    if (featuresSection) {
        const headerHeight = document.querySelector('.navbar').offsetHeight;
        const targetPosition = featuresSection.offsetTop - headerHeight;
        
        window.scrollTo({
            top: targetPosition,
            behavior: 'smooth'
        });
    }
}

function scrollToAbout() {
    const aboutSection = document.querySelector('#about');
    if (aboutSection) {
        const headerHeight = document.querySelector('.navbar').offsetHeight;
        const targetPosition = aboutSection.offsetTop - headerHeight;
        
        window.scrollTo({
            top: targetPosition,
            behavior: 'smooth'
        });
    }
}

// Navbar Background on Scroll
window.addEventListener('scroll', function() {
    const navbar = document.querySelector('.navbar');
    if (window.scrollY > 50) {
        navbar.style.backgroundColor = 'rgba(44, 62, 80, 0.95)';
        navbar.style.backdropFilter = 'blur(10px)';
    } else {
        navbar.style.backgroundColor = '#2c3e50';
        navbar.style.backdropFilter = 'none';
    }
});

// Parallax Effect for Hero Section Only (disabled for features section)
window.addEventListener('scroll', function() {
    const scrolled = window.pageYOffset;
    const hero = document.querySelector('.hero');
    const parallaxSpeed = 0.5;
    
    // Apply parallax only to the hero section, not to the features section
    if (hero) {
        hero.style.transform = `translateY(${scrolled * parallaxSpeed}px)`;
    }
    
    // Ensure features section stays fixed and doesn't move with scroll
    const features = document.querySelector('.features');
    if (features) {
        features.style.transform = 'none';
    }
});

// Add CSS animations (modified for features section stability)
const style = document.createElement('style');
style.textContent = `
    .animate-in {
        animation: slideInUp 0.6s ease-out forwards;
    }
    
    @keyframes slideInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .typing-cursor {
        animation: blink 1s infinite;
    }
    
    @keyframes blink {
        0%, 50% { opacity: 1; }
        51%, 100% { opacity: 0; }
    }
    
    .feature-card {
        transition: box-shadow 0.3s ease, border-color 0.3s ease;
        transform: none !important; /* Prevent any transform */
    }
    
    .features {
        position: relative;
        z-index: 2;
        background: #f8f9fa;
        transform: none !important; /* Ensure features section doesn't move */
    }
    
    .feature-card:hover {
        box-shadow: 0 15px 30px rgba(0,0,0,0.2);
        border-color: #3498db;
    }
    
    .primary-feature:hover {
        box-shadow: 0 10px 25px rgba(0,0,0,0.15);
    }
`;
document.head.appendChild(style);



// Error Handling
window.addEventListener('error', function(e) {
    console.error('Homepage error:', e.error);
});

// Performance monitoring
if (window.performance) {
    window.addEventListener('load', function() {
        const loadTime = window.performance.timing.loadEventEnd - window.performance.timing.navigationStart;
        console.log('Homepage load time:', loadTime + 'ms');
    });
}
