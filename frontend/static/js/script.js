document.addEventListener('DOMContentLoaded', () => {

    // Handle data visualization switching
    function loadVisualization(dataset) {
        const visualizationImage = document.getElementById('visualizationImage');
        const loadingMessage = document.getElementById('loadingMessage');

        console.log(`Loading visualization for dataset: ${dataset}`); // Log the dataset being loaded

        // Display loading message while the image is being loaded
        loadingMessage.style.display = 'block';
        visualizationImage.style.display = 'none';

        // Prevent caching by appending a timestamp to the URL
        const timestamp = new Date().getTime();
        const imageUrl = `/visualize?dataset=${dataset}&_=${timestamp}`;

        // Update the image source URL
        visualizationImage.src = imageUrl;

        // Once the image is loaded, hide the loading message
        visualizationImage.onload = () => {
            console.log(`Visualization for ${dataset} loaded successfully.`);
            loadingMessage.style.display = 'none';
            visualizationImage.style.display = 'block';
        };

        // If there's an error loading the image, show an error message
        visualizationImage.onerror = () => {
            console.error(`Failed to load visualization for dataset: ${dataset}`);
            loadingMessage.style.display = 'none';
            visualizationImage.style.display = 'none';
            alert("Failed to load the visualization. Please try again.");
        }
    }

    // Attach click event listeners to the buttons
    const visualizationButtons = document.querySelectorAll('.visualization-button');
    visualizationButtons.forEach(button => {
        button.addEventListener('click', (event) => {
            const dataset = event.target.getAttribute('data-dataset');
            loadVisualization(dataset);

            // Update button styling for active selection
            visualizationButtons.forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
        });
    });

    // Load the default visualization (Years Reduced by County) on page load
    loadVisualization('years_reduced');
});
