---
marp: true
theme: default
paginate: true
---

## Introduction to linux OS
- **Linux** is a free, open-source operating system kernel that forms the core of numerous distributions, powering everything from smartphones to supercomputers with its modular design
- It's critically important as it runs over **90% of the world's cloud infrastructure** and forms the backbone of modern web services, enterprise systems, and Android devices
- An interesting fact: all **500 of the world's fastest supercomputers** have run on Linux since 2017, demonstrating its unparalleled performance and scalability

<!-- NARRATION: Welcome to our introduction to Linux! Did you know Linux is a free, open-source operating system that powers everything from smartphones to supercomputers? It's incredibly important—over 90% of the world's cloud infrastructure runs on it. And here's a cool fact: since 2017, all 500 of the world's fastest supercomputers have used Linux. That shows just how powerful and scalable this system is! -->

---

## Key Concepts
- The **Linux kernel** is the core component that manages hardware resources and system processes, providing a stable foundation for all operations and enabling efficient multitasking and hardware communication across diverse devices.
- The **file system hierarchy** organizes all data and devices into a unified tree structure starting from the root directory (/), which standardizes locations for system files, configurations, and user data to ensure consistency and simplify navigation and management.
- **User and permission management** controls access to system resources through user accounts, groups, and read/write/execute privileges, which is critical for maintaining security, preventing unauthorized changes, and enabling multi-user environments safely.

<!-- NARRATION: Let's look at some key parts of Linux. The kernel is the core that manages hardware and processes. The file system organizes everything into a tree structure starting from the root directory. And user and permission management keeps things secure by controlling who can access what. These features make Linux stable and safe for multi-user environments. -->

---

## How linux OS Works
- **Bootloader Initialization**: The bootloader loads the Linux kernel into memory and starts it, which is essential for transitioning the hardware from a powered-off state to a running operating system.
- **Kernel and System Startup**: The kernel initializes hardware, mounts the filesystem, and launches the **init system** (like systemd), which manages all subsequent processes and services required for a functional user environment.
- **User Space and Login**: The init system starts the login prompt or display manager, allowing users to authenticate and access the shell or desktop, enabling interaction with applications and system resources.

<!-- NARRATION: So how does Linux actually work? It starts with the bootloader loading the kernel into memory. Then the kernel initializes hardware and starts the init system, which manages all processes. Finally, the login prompt appears, letting users access the system. This process ensures a smooth and functional environment for everyone. -->

---

## Examples of linux OS
- **CentOS**: A free, community-supported distribution derived from Red Hat Enterprise Linux (RHEL), known for its **stability and reliability** in enterprise environments. It is highly relevant for servers and production systems where long-term support and predictability are critical.
- **Arch Linux**: A lightweight, flexible distribution designed for users who prefer a **do-it-yourself approach**, offering a rolling release model and extensive customization. Its relevance is in providing deep control over the system, appealing to advanced users and developers seeking minimalism and up-to-date software.

<!-- NARRATION: There are many versions of Linux, called distributions. For example, CentOS is known for stability and is great for servers. Arch Linux is for those who love customization and a do-it-yourself approach. Each distribution offers something different, catering to various needs from enterprise to personal use. -->

---

## Summary: linux OS
- Linux is an **open-source** operating system, meaning its source code is freely available for anyone to view, modify, and distribute; this fosters a collaborative global community of developers who continuously improve and secure the system, making it highly adaptable and resilient for both personal and enterprise use.
- It offers exceptional **stability and security** due to its Unix-like architecture and rigorous permission and user role management; this design minimizes system crashes and limits the impact of malware, which is why it powers the majority of web servers, supercomputers, and critical infrastructure worldwide.
- Linux provides unparalleled **customization and flexibility**, with hundreds of distributions (distros) and desktop environments to choose from; this allows users to tailor the operating system precisely to their hardware and workflow needs, promoting efficiency and reducing resource overhead compared to proprietary alternatives.

<!-- NARRATION: In summary, Linux is open-source, meaning anyone can view and modify its code. It's stable and secure, thanks to its design, which is why it powers most web servers and supercomputers. Plus, it's highly customizable with hundreds of distributions to choose from, making it flexible for any user. -->
