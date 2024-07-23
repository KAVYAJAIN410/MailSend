document.addEventListener('DOMContentLoaded', (event) => {
    const subjectInput = document.getElementById('subject');
    const contentInput = document.getElementById('content');
    const dropdown = document.getElementById('dropdown');

    const tags = dropdown.getAttribute('data-tags').split(',');

    function showDropdown(inputElement) {
        const value = inputElement.value;
        const cursorPosition = inputElement.selectionStart;
        const substring = value.slice(0, cursorPosition);

        if (substring.endsWith('{{')) {
            dropdown.style.display = 'block';
            const rect = inputElement.getBoundingClientRect();
            dropdown.style.left = `${rect.left}px`;
            dropdown.style.top = `${rect.bottom}px`;
        } else {
            dropdown.style.display = 'none';
        }
    }

    function insertTag(tag, inputElement) {
        const value = inputElement.value;
        const cursorPosition = inputElement.selectionStart;
        const newValue = value.slice(0, cursorPosition) + tag + value.slice(cursorPosition);
        inputElement.value = newValue;
        dropdown.style.display = 'none';
    }

    subjectInput.addEventListener('input', () => showDropdown(subjectInput));
    contentInput.addEventListener('input', () => showDropdown(contentInput));

    tags.forEach(tag => {
        const tagElement = document.createElement('div');
        tagElement.classList.add('dropdown-item');
        tagElement.innerText = `{{ ${tag} }}`;
        tagElement.addEventListener('click', () => {
            insertTag(`{{ ${tag} }}`, subjectInput);
            insertTag(`{{ ${tag} }}`, contentInput);
        });
        dropdown.appendChild(tagElement);
    });

    document.addEventListener('click', (event) => {
        if (!dropdown.contains(event.target) && event.target !== subjectInput && event.target !== contentInput) {
            dropdown.style.display = 'none';
        }
    });
});
