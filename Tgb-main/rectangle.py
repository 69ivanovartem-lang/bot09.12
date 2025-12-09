class Rectangle:  
    def __init__(self, width, height):  
        self.width = width  
        self.height = height  
    def calculate_area(self):  
        return self.width * self.height  
    def print_perimeter(self):  
        p = 2 * (self.width + self.height)  