---
marp: true
theme: default
paginate: true
---

## Introduction to Binary Search
- **Binary search** is an efficient algorithm for finding an item in a sorted list
- Works by repeatedly dividing the search interval in half
- **Time complexity**: O(log n), making it much faster than linear search for large datasets
- **Prerequisite**: The list must be sorted for the algorithm to work correctly

<!-- NARRATION: Welcome to binary search! This is a super efficient way to find items in sorted lists. Instead of checking every single element like linear search, it cleverly halves the search area each time. That means for a list of a million items, it only needs about 20 comparisons! But remember - your list absolutely must be sorted first, otherwise this clever algorithm just won't work properly. -->

---

## Algorithm Steps
1. Set **low** to the first index and **high** to the last index of the list
2. While **low** ≤ **high**:
   - Calculate **mid** = (low + high) // 2
   - If the element at **mid** equals the target, return mid
   - If the target is less than the element at mid, set **high** = mid - 1
   - If the target is greater, set **low** = mid + 1
3. If the loop ends, return -1 (target not found)

<!-- NARRATION: Here's how binary search works step by step. First, we set our boundaries - low at the start and high at the end. Then we enter a loop where we calculate the middle point. If we find our target there, great! If not, we eliminate half the list and try again. It's like playing 'higher or lower' but with numbers - each guess tells us exactly which half to search next. -->

---

## Pseudocode
function binarySearch(arr, target):
    low = 0
    high = len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
- Important point 1
- Key detail 2
- Additional information

<!-- NARRATION: Let's look at the actual pseudocode. We start by setting our low and high pointers. Then we enter a while loop that continues as long as low doesn't pass high. Inside, we calculate mid, check if we found our target, and adjust our search range accordingly. The beauty is in how simple the code is - just a few lines that can search massive datasets incredibly quickly! -->

---

## Advantages and Limitations
- **Advantages**:
  - Extremely efficient for large sorted datasets
  - Simple to implement and understand
  - Low memory usage (iterative version)
- **Limitations**:
  - Requires the list to be sorted beforehand
  - Not suitable for linked lists (requires random access)
  - Overkill for very small lists

<!-- NARRATION: Binary search has some great advantages - it's lightning fast for big datasets and uses very little memory. But there are limitations too. Your data must be sorted first, which takes time. It doesn't work well with linked lists because we need random access. And for very small lists, simpler methods might actually be faster. So choose the right tool for the job! -->

---

## Common Mistakes to Avoid
- Forgetting to ensure the list is sorted
- Incorrect calculation of the mid index (risk of integer overflow)
- Off-by-one errors in updating low/high pointers
- Using recursion without considering stack depth for large lists
- Not handling the case when the target is not present

<!-- NARRATION: Watch out for these common mistakes! Always check that your list is sorted first - binary search fails on unsorted data. Be careful calculating mid to avoid integer overflow. Make sure you update your pointers correctly - it's easy to be off by one. And don't forget to handle the case when the item isn't in the list at all! -->

---

## Key Takeaways
- Binary search dramatically reduces search time in sorted data
- Fundamental concept in computer science and algorithm design
- Foundation for more advanced algorithms and data structures
- Mastery requires understanding both iterative and recursive approaches
- Always verify preconditions (sorted input) before implementation

<!-- NARRATION: To sum up: binary search is a fundamental algorithm that's incredibly powerful for sorted data. It forms the basis for many advanced algorithms and data structures you'll learn later. Whether you use the iterative or recursive version, the key is understanding how it works. Always remember the golden rule - sorted input first! Master this, and you've got a valuable tool for efficient searching. -->
