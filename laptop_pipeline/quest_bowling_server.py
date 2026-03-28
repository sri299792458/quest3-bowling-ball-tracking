try:
    from .quest_bowling_udp_server import main
except ImportError:
    from quest_bowling_udp_server import main


if __name__ == "__main__":
    main()
